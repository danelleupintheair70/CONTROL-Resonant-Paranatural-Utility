"""Audio track languages: read from Plex, grouped by language, rewritten on request."""

import json
import shutil
import subprocess
import time

import pytest

from doblarr import audio_languages as al
from doblarr import plex_library
from doblarr.clients.plex import PlexClient


def _stream(code, title, channels=2, default=False):
    return {"streamType": 2, "languageCode": code, "title": title, "channels": channels,
            "default": default}


class FakePlex:
    external_ids = staticmethod(PlexClient.external_ids)
    audio_languages = staticmethod(PlexClient.audio_languages)

    def __init__(self, streams):
        self.streams, self.probed, self.refreshed = streams, [], []

    def sections(self):
        return [{"key": "1", "type": "movie", "title": "Movies"},
                {"key": "2", "type": "show", "title": "TV"}]

    def section_items(self, key):
        if key == "1":
            return [{"ratingKey": "10", "title": "Quiet Tide", "year": 2001, "updatedAt": 1,
                     "Guid": [{"id": "tmdb://77"}], "Media": [{"Part": [{"file": "/m/tide.mkv"}]}]}]
        return [{"ratingKey": "20", "title": "Harbor Lights", "Guid": [{"id": "tvdb://88"}]}]

    def leaves(self, key):
        return [{"ratingKey": str(k), "updatedAt": 1,
                 "Media": [{"Part": [{"file": f"/s/e{k}.mkv"}]}]} for k in (21, 22)]

    def metadata(self, key):
        self.probed.append(key)
        return {"Media": [{"Part": [{"file": "f", "Stream": self.streams[key]}]}]}


STREAMS = {
    "10": [_stream("und", "Stereo", default=True), _stream("eng", "Korean", 6)],
    "21": [_stream("jpn", "Japanese", default=True), _stream("spa", "Latino")],
    "22": [_stream("jpn", "Japanese", default=True), _stream("spa", "Esp LAT")],
}


def test_a_title_naming_a_language_wins_over_the_tag():
    assert al.title_language("Esp LAT") == "es-419"
    assert al.title_language("[Group] 2.0 ENG - FLAC") == "en"
    assert al.title_language("Stereo") is None
    moved = al.classify({"lang": "eng", "title": "Korean"}, None)
    assert moved == {"lang": "ko", "mismatch": True, "kind": ""}
    assert al.classify({"lang": "spa", "title": "Spanish AI"}, "ja")["kind"] == "AI"
    assert al.classify({"lang": "jpn", "title": ""}, "ja")["kind"] == "Original"
    assert al.track_name("es-419") == "Spanish (Latin America)"
    assert al.track_name("es-ES") == "Spanish (Spain)"


def test_tracks_are_grouped_by_language_and_cached_by_file(tmp_path):
    plex = FakePlex(STREAMS)
    cache = plex_library.AudioCache(tmp_path / "plex-audio.json")
    originals = lambda item, movie: "ja" if not movie else None  # noqa: E731
    rows = al.read_tracks(plex, cache, originals)
    assert sorted(plex.probed) == ["10", "21", "22"]
    summary = al.summarize(rows)
    buckets = {b["lang"]: b for b in summary["buckets"]}
    assert summary["buckets"][0]["lang"] == "und"
    assert [v["title"] for v in buckets["es-419"]["variants"]] == ["Latino", "Esp LAT"]
    assert buckets["es-419"]["variants"][0]["where"] == [{"label": "Harbor Lights", "tracks": 1}]
    assert buckets["ja"]["variants"][0]["kind"] == "Original"
    assert buckets["ko"]["variants"][0]["mismatch"] is True
    assert summary["totals"]["und"] == 1
    assert summary["totals"]["mismatched_tag"] == 1

    # A second read asks Plex nothing: every file's tracks are cached.
    again = FakePlex(STREAMS)
    al.read_tracks(again, plex_library.AudioCache(tmp_path / "plex-audio.json"), originals)
    assert again.probed == []


def _service(tmp_path, streams=STREAMS, dry_run=False):
    plex = FakePlex(streams)
    cache = plex_library.AudioCache(tmp_path / "plex-audio.json")
    return plex, al.AudioLanguages(lambda: plex, lambda: cache, lambda i, m: None,
                                   lambda: dry_run, refresh=plex.refreshed.append)


def test_a_plan_lists_each_files_edits_and_refuses_a_stale_page(tmp_path):
    _plex, service = _service(tmp_path)
    scan = service.scan()
    latino = next(b for b in scan["buckets"] if b["lang"] == "es-419")
    ids = [v["id"] for v in latino["variants"]]
    changes = [{"id": i, "language": "es-419", "title": "Spanish (Latin America) 2.0"} for i in ids]
    plan = service.plan(scan["scanned_at"], changes)
    # Both episodes' files are named "f" by the fake; each carries one edit.
    assert list(plan) == ["f"] and len(plan["f"]) == 2
    edit = plan["f"][0]
    assert edit["tag"] == "spa" and edit["title"] == "Spanish (Latin America) 2.0"
    with pytest.raises(ValueError):
        service.plan("yesterday", changes)
    with pytest.raises(ValueError):
        service.plan(scan["scanned_at"], [{"id": ids[0], "language": "xx-YY", "title": "x"}])


def test_dry_run_plans_without_writing(tmp_path):
    _plex, service = _service(tmp_path, dry_run=True)
    scan = service.scan()
    vid = scan["buckets"][0]["variants"][0]["id"]
    change = {"id": vid, "language": "ja", "title": "Japanese 2.0"}
    job = service.start(scan["scanned_at"], [change])
    assert job["state"] == "planned" and job["tracks"] == 1


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type:stream_tags=language,title", "-of", "json", str(path)],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [s.get("tags", {}) for s in json.loads(out)["streams"] if s["codec_type"] == "audio"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_rewrite_sets_tag_and_title_and_refuses_a_changed_file(tmp_path):
    film = tmp_path / "film.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", "-f", "lavfi",
                    "-i", "sine=d=1:f=300", "-map", "0", "-map", "1", "-c:a", "flac",
                    "-metadata:s:a:0", "language=und", "-metadata:s:a:0", "title=Stereo",
                    "-metadata:s:a:1", "language=spa", "-metadata:s:a:1", "title=Latino",
                    str(film)], check=True)
    edits = [{"key": "1", "pos": 1, "was_tag": "spa", "was_title": "Latino",
              "tag": "spa", "title": "Spanish (Latin America) 2.0"},
             {"key": "1", "pos": 0, "was_tag": "und", "was_title": "Stereo",
              "tag": "jpn", "title": "Japanese 2.0"}]
    al.rewrite(film, edits)
    tags = _probe(film)
    assert tags[0]["language"] == "jpn" and tags[0]["title"] == "Japanese 2.0"
    assert tags[1]["title"] == "Spanish (Latin America) 2.0"
    assert not (tmp_path / "film.partial.mkv").exists()
    # The same edits again no longer match what the file says: refused, untouched.
    with pytest.raises(ValueError):
        al.rewrite(film, edits)
    assert _probe(film)[0]["title"] == "Japanese 2.0"


def test_the_route_scans_and_applies(client_factory, monkeypatch):
    client = client_factory({"dub": {"dry_run": False}})
    client.app.state.services._cache["plex"] = FakePlex(STREAMS)
    written = []
    monkeypatch.setattr(al, "rewrite", lambda path, edits: written.append((str(path), edits)))
    data = client.get("/api/audio-languages").json()
    assert data["totals"]["tracks"] == 6
    assert any(lang["id"] == "es-419" for lang in data["languages"])
    vid = data["buckets"][0]["variants"][0]["id"]
    res = client.post("/api/audio-languages/apply", json={
        "scanned_at": data["scanned_at"],
        "changes": [{"id": vid, "language": "ja", "title": "Japanese 2.0"}]})
    assert res.status_code == 200
    for _ in range(50):
        if client.get("/api/audio-languages/apply").json()["state"] == "done":
            break
        time.sleep(0.05)
    assert [path for path, _edits in written] == ["f"]
    stale = client.post("/api/audio-languages/apply", json={"scanned_at": "old", "changes": []})
    assert stale.status_code == 422

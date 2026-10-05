"""Watching a finished dub: a browser copy per language, the quiet spans, notes."""

import shutil
import subprocess
import time

import pytest

from doblarr import watch


def test_a_span_counts_only_after_the_overall_difference_is_taken_out():
    original = [-20.0] * 40
    ours = [-22.0] * 40                     # mixed 2 dB lower overall: not a lost sound
    ours[10:16] = [-40.0] * 6               # 1.5 s of laugh nobody voiced
    found = watch.quieter(original, ours)
    assert found["offset_db"] == 2.0
    assert found["spans"] == [{"start": 2.5, "end": 4.0, "quieter_db": 18.0}]
    # Too short to bother a person with.
    ours[30] = -40.0
    assert len(watch.quieter(original, ours)["spans"]) == 1


def _dub(path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440", "-f", "lavfi", "-i", "sine=frequency=660",
         "-t", "3", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264",
         "-c:a", "aac", "-metadata:s:a:0", "language=jpn", "-metadata:s:a:1", "language=spa",
         "-metadata:s:a:1", "title=Spanish AI", "-disposition:a:0", "default", str(path)],
        check=True, capture_output=True)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_dub_is_watched_in_any_language_and_notes_are_kept(tmp_path, client_factory):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    output = out_dir / "harbor-lights-e02.mkv"
    _dub(output)
    client = client_factory({"paths": {"output_dir": str(out_dir)}})
    jobs = client.app.state.jobs
    job = jobs.add(title="Harbor Lights e02", source="t", source_lang="ja", target_lang="es")
    jobs.update(job.id, status="done", output_file=str(output))
    for _ in range(120):
        info = client.get(f"/api/watch/{job.id}").json()
        if info["state"] != "preparing":
            break
        time.sleep(0.25)
    assert info["state"] == "ready", info["state"]
    tracks = {t["title"] or t["lang"]: t for t in info["tracks"]}
    assert tracks["Spanish AI"]["ours"] and tracks["ja"]["original"]
    assert info["loudness"]["spans"] == []
    assert info["job"]["source"] == "ja" and info["job"]["target"] == "es"
    assert info["job"]["has_review"] is False and info["job"]["version"] == ""
    clip = client.get(f"/api/watch/{job.id}/audio/{tracks['Spanish AI']['stream']}.mp4",
                      headers={"Range": "bytes=0-99"})
    assert clip.status_code == 206 and len(clip.content) == 100
    saved = client.post(f"/api/watch/{job.id}/notes", json={
        "at": 1.5, "category": "lost sound", "note": "the laugh is gone",
        "in_original": "no", "track": "Spanish AI"}).json()["note"]
    assert saved["resolution"] == "open"
    patched = client.patch(f"/api/watch/{job.id}/notes/{saved['id']}", json={
        "resolution": "fixed", "base_revision": saved["revision"]}).json()["note"]
    assert patched["resolution"] == "fixed"
    notes = client.get(f"/api/watch/{job.id}").json()["notes"]
    assert [(n["note"], n["resolution"]) for n in notes] == [("the laugh is gone", "fixed")]

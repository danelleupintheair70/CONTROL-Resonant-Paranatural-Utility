"""Canonical media and character identity: paths are locations, not identities."""

import json

import pytest

from doblarr import identity, identity_migration, voice_tags
from doblarr.store import Database
from doblarr.studio import records


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "id.db")
    yield database
    database.close()


def _file(path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_the_same_content_at_two_places_is_one_revision(db, tmp_path):
    first = _file(tmp_path / "lib" / "Harbor Lights" / "Season 01" / "e01.mkv", b"a" * 5000)
    found = identity.resolve(db, first)
    copy = _file(tmp_path / "copies" / "renamed.mkv", b"a" * 5000)
    moved = identity.resolve(db, copy)
    assert moved["revision_id"] == found["revision_id"]
    assert moved["media_id"] == found["media_id"] and moved["how"] == "content"
    media = records.get(db, "media", found["media_id"])
    assert len(media["revisions"][found["revision_id"]]["locations"]) == 2


def test_two_files_with_one_name_never_share_an_identity(db, tmp_path):
    one = _file(tmp_path / "a" / "Season 01" / "e01.mkv", b"one" * 2000)
    two = _file(tmp_path / "b" / "Season 01" / "e01.mkv", b"two" * 2000)
    first, second = identity.resolve(db, one), identity.resolve(db, two)
    assert first["media_id"] != second["media_id"]
    assert first["revision_id"] != second["revision_id"]


def test_two_shows_filed_under_the_same_folder_name_are_two_series(db, tmp_path):
    one = _file(tmp_path / "nas1" / "Harbor Lights" / "Season 01" / "e01.mkv", b"x" * 3000)
    two = _file(tmp_path / "nas2" / "Harbor Lights" / "Season 01" / "e01.mkv", b"y" * 3000)
    assert identity.resolve(db, one)["series_id"] != identity.resolve(db, two)["series_id"]


def test_new_content_at_a_known_place_is_a_new_revision_of_the_same_media(db, tmp_path):
    path = _file(tmp_path / "Harbor Lights" / "e01.mkv", b"first cut" * 1000)
    before = identity.resolve(db, path)
    path.write_bytes(b"director's cut" * 1000)
    after = identity.resolve(db, path)
    assert after["media_id"] == before["media_id"] and after["how"] == "location"
    assert after["revision_id"] != before["revision_id"]
    assert set(records.get(db, "media", before["media_id"])["revisions"]) == {
        before["revision_id"], after["revision_id"]}


def test_provider_ids_decide_the_series_and_the_episode(db, tmp_path):
    path = _file(tmp_path / "Whatever" / "Harbor Lights - S02E05.mkv", b"z" * 4000)
    found = identity.resolve(db, path, hints={"tvdb_id": 4242})
    assert found["series_id"] == "show:tvdb:4242"
    assert found["media_id"] == "ep:tvdb:4242:s2e5"
    assert (found["season"], found["episode"]) == (2, 5)
    assert identity.episode_order(db, found["media_id"]) == (2, 5)


def test_editions_are_read_from_the_name_only_as_a_hint(db, tmp_path):
    path = _file(tmp_path / "Movie (2001) Director's Cut.mkv", b"m" * 4000)
    assert identity.resolve(db, path, hints={"kind": "movie"})["edition"] == "director's cut"


def test_characters_keep_their_id_through_renames_and_merges(db):
    series = "show:tvdb:1"
    kaito = identity.ensure_character(db, series, "Kaito")
    assert identity.ensure_character(db, series, " kaito ")["id"] == kaito["id"]
    renamed = identity.rename_character(db, kaito["id"], "Kaito Mori",
                                        base_revision=kaito["revision"])
    assert renamed["id"] == kaito["id"] and "Kaito" in renamed["aliases"]
    assert identity.find_character(db, series, "kaito")["id"] == kaito["id"]
    # Another series has its own Kaito.
    assert identity.ensure_character(db, "show:tvdb:2", "Kaito")["id"] != kaito["id"]
    twin = identity.ensure_character(db, series, "K.")
    identity.merge_characters(db, kaito["id"], twin["id"], base_revision=renamed["revision"])
    assert identity.resolve_character(db, twin["id"])["id"] == kaito["id"]
    assert all(c["id"] != twin["id"] for c in identity.characters(db, series))


def test_a_stale_character_edit_conflicts_instead_of_overwriting(db):
    mina = identity.ensure_character(db, "show:tvdb:1", "Mina")
    identity.rename_character(db, mina["id"], "Mina Sato", base_revision=mina["revision"])
    with pytest.raises(records.StudioConflict):
        identity.rename_character(db, mina["id"], "Minami", base_revision=mina["revision"])


def test_a_manual_link_is_never_replaced_by_a_proposal(db):
    ren = identity.ensure_character(db, "s", "Ren")
    sora = identity.ensure_character(db, "s", "Sora")
    identity.associate(db, "rev-1", "cluster", "SPEAKER_00", ren["id"], state="manual")
    identity.associate(db, "rev-1", "cluster", "SPEAKER_00", sora["id"], state="proposed")
    assert identity.cluster_characters(db, "rev-1")["SPEAKER_00"]["id"] == ren["id"]


def _legacy_names(db, name, names, lines=None):
    db.save_plan("speaker-names:" + name, name, {"names": names, "lines": lines or {}})


def _script(work, folder, media_path):
    path = work / "media" / folder / "es-419" / (media_path.stem + ".script.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"identity": {"input": str(media_path)}, "segments": []}),
                    encoding="utf-8")


def test_legacy_names_migrate_only_when_their_file_is_unambiguous(db, tmp_path):
    work = tmp_path / "work"
    episode = _file(tmp_path / "Harbor Lights" / "Season 01" / "e01.mkv", b"e1" * 3000)
    _script(work, "a", episode)
    dup_a = _file(tmp_path / "x" / "Season 01" / "e09.mkv", b"9a" * 3000)
    dup_b = _file(tmp_path / "y" / "Season 01" / "e09.mkv", b"9b" * 3000)
    _script(work, "b", dup_a)
    _script(work, "c", dup_b)
    _legacy_names(db, "e01.mkv", {"SPEAKER_00": "Kaito", "SPEAKER_01": "Mina"},
                  {"cue-7": "Mina"})
    _legacy_names(db, "e09.mkv", {"SPEAKER_00": "Ren"})
    plan = identity_migration.preview(db, work)
    states = {a["key"]: a["state"] for a in plan["actions"]}
    assert states["speaker-names:e01.mkv"] == "ready"
    assert states["speaker-names:e09.mkv"] == "ambiguous"
    # Nothing was written by the preview.
    assert not records.list_latest(db, "association")
    result = identity_migration.apply(db, work, plan["fingerprint"])
    assert result["applied"] == ["speaker-names:e01.mkv"]
    ident = identity.resolve(db, episode)
    linked = identity.cluster_characters(db, ident["revision_id"])
    assert {k: v["name"] for k, v in linked.items()} == {"SPEAKER_00": "Kaito",
                                                          "SPEAKER_01": "Mina"}
    again = identity_migration.preview(db, work)
    assert {a["key"]: a["state"] for a in again["actions"]}["speaker-names:e01.mkv"] == "applied"
    revisions = len(db.query("SELECT * FROM studio_records WHERE kind='association'"))
    identity_migration.apply(db, work, again["fingerprint"])
    assert len(db.query("SELECT * FROM studio_records WHERE kind='association'")) == revisions


def test_a_migration_refuses_a_preview_that_went_stale(db, tmp_path):
    work = tmp_path / "work"
    episode = _file(tmp_path / "Show" / "e01.mkv", b"q" * 3000)
    _script(work, "a", episode)
    _legacy_names(db, "e01.mkv", {"SPEAKER_00": "Kaito"})
    plan = identity_migration.preview(db, work)
    _legacy_names(db, "e01.mkv", {"SPEAKER_00": "Tomoe"})
    with pytest.raises(identity_migration.StalePreview):
        identity_migration.apply(db, work, plan["fingerprint"])


def test_legacy_prints_move_to_the_series_without_mixing_languages(db, tmp_path):
    work = tmp_path / "work"
    episode = _file(tmp_path / "Harbor Lights" / "Season 01" / "e01.mkv", b"p" * 3000)
    _script(work, "a", episode)
    db.save_plan("voice-tags:harbor lights", "Harbor Lights", {"models": {"m": {
        "e01.mkv": {"Kaito": {"sum": [1.0, 0.0], "n": 3}}}}})
    plan = identity_migration.preview(db, work)
    action = next(a for a in plan["actions"] if a["kind"] == "prints")
    assert action["state"] == "ready"
    identity_migration.apply(db, work, plan["fingerprint"])
    known = voice_tags.prints_series(db, action["series_id"], "m", "")
    kaito = identity.find_character(db, action["series_id"], "Kaito")
    assert list(known) == [kaito["id"]]
    assert voice_tags.prints_series(db, action["series_id"], "m", "ja") == {}


def test_a_titles_cast_becomes_series_choices_only_for_identified_characters(db, tmp_path):
    from doblarr.studio import casting

    work = tmp_path / "work"
    episode = _file(tmp_path / "Harbor Lights" / "Season 01" / "e03.mkv", b"c3" * 3000)
    _script(work, "a", episode)
    db.save_cast(str(episode), "e03", [
        {"speaker_id": "SPEAKER_00", "voice": "v-kaito"},
        {"speaker_id": "SPEAKER_04", "voice": "v-guard"}])
    unlinked = identity_migration.preview(db, work)
    cast = next(a for a in unlinked["actions"] if a["kind"] == "cast")
    assert cast["state"] == "unlinked"           # nobody is identified yet
    ident = identity.resolve(db, episode)
    kaito = identity.ensure_character(db, ident["series_id"], "Kaito")
    identity.associate(db, ident["revision_id"], "cluster", "SPEAKER_00", kaito["id"])
    plan = identity_migration.preview(db, work)
    cast = next(a for a in plan["actions"] if a["kind"] == "cast")
    assert cast["state"] == "ready" and cast["characters"] == {"SPEAKER_00": "Kaito"}
    identity_migration.apply(db, work, plan["fingerprint"])
    choices = records.get(db, "casting", casting.record_id("series", ident["series_id"]))
    assert choices["characters"]["Kaito"]["voice"] == "v-kaito"
    assert "SPEAKER_04" not in choices["characters"]     # a number is not a character


def test_a_local_series_joins_a_provider_series_only_when_confirmed(db, tmp_path):
    work = tmp_path / "work"
    episode = _file(tmp_path / "Harbor Lights" / "Season 01" / "e01.mkv", b"L1" * 3000)
    _script(work, "a", episode)
    _legacy_names(db, "e01.mkv", {"SPEAKER_00": "Kaito", "SPEAKER_01": "Mina"})
    db.save_plan("voice-traits:profile:p1", "t", {"show": "tvdb-555", "character": "KAITO"})
    plan = identity_migration.preview(db, work)
    link = next(a for a in plan["actions"] if a["kind"] == "series_link")
    assert link["state"] == "confirm" and link["target"] == "show:tvdb:555"
    # Applying without confirming leaves the local series alone.
    identity_migration.apply(db, work, plan["fingerprint"])
    local = identity.resolve(db, episode)["series_id"]
    assert local.startswith("show:local:")
    plan = identity_migration.preview(db, work)
    identity_migration.apply(db, work, plan["fingerprint"],
                             keys=[a["key"] for a in plan["actions"]])
    now = identity.resolve(db, episode)
    assert now["series_id"] == "show:tvdb:555"
    kaito = identity.find_character(db, "show:tvdb:555", "kaito")
    assert kaito is not None
    linked = identity.cluster_characters(db, now["revision_id"])
    assert linked["SPEAKER_00"]["id"] == kaito["id"]
    assert identity.find_character(db, "show:tvdb:555", "Mina") is not None

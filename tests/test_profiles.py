"""Character voice profiles: twelve groups, explicit updates, locks, no speech on read."""

from types import SimpleNamespace

import pytest

from doblarr import identity, profiles
from doblarr.models import Segment
from doblarr.store import Database
from doblarr.studio import casting, records


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "p.db")
    yield database
    database.close()


def test_an_empty_profile_has_every_group_and_unknown_values(db):
    kaito = identity.ensure_character(db, "show:tvdb:1", "Kaito")
    profile = profiles.get(db, kaito["id"])
    assert set(profiles.GROUPS) <= set(profile)
    assert profile["vocal"]["perceived_age"] == "unknown" and profile["revision"] == 0
    assert set(profile["variations"]) == set(profiles.VARIATIONS)


def test_fields_round_trip_and_unnamed_fields_survive(db):
    mina = identity.ensure_character(db, "s", "Mina")
    first = profiles.update(db, mina["id"], base_revision=0, set_fields={
        "vocal.brightness": "bright", "vocal.pitch_range": {"low": 180, "high": 320,
                                                           "units": "Hz"},
        "delivery.pace": "quick", "locale.desired_locale": "es-MX",
        "variations.whisper.desired": True, "engine.pitch_semitones": 2,
        "pronunciation.terms": [{"term": "Mina", "spoken": "Mína", "locale": "es-MX"}],
        "templates.favored": [{"template": "voice/late-emphasis"}]})
    second = profiles.update(db, mina["id"], base_revision=first["revision"],
                             set_fields={"delivery.energy": "high"})
    assert second["vocal"]["brightness"] == "bright"
    assert second["vocal"]["pitch_range"]["high"] == 320
    assert second["variations"]["whisper"]["desired"] is True
    assert second["pronunciation"]["terms"][0]["spoken"] == "Mína"
    assert second["delivery"]["pace"] == "quick" and second["delivery"]["energy"] == "high"
    assert second["meta"]["fields"]["delivery.energy"]["source"] == "manual"


def test_a_stale_profile_write_conflicts(db):
    ren = identity.ensure_character(db, "s", "Ren")
    profiles.update(db, ren["id"], base_revision=0, set_fields={"delivery.pace": "slow"})
    with pytest.raises(records.StudioConflict):
        profiles.update(db, ren["id"], base_revision=0, set_fields={"delivery.pace": "quick"})


def test_invalid_values_are_refused(db):
    sora = identity.ensure_character(db, "s", "Sora")
    with pytest.raises(ValueError):
        profiles.update(db, sora["id"], base_revision=0,
                        set_fields={"vocal.brightness": "sparkly"})
    with pytest.raises(ValueError):
        profiles.update(db, sora["id"], base_revision=0, set_fields={"meta.fields": {}})
    with pytest.raises(ValueError):
        profiles.update(db, sora["id"], base_revision=0,
                        set_fields={"dynamics.max_boost_db": float("nan")})


def test_a_locked_field_is_never_changed_by_a_proposal(db):
    tomoe = identity.ensure_character(db, "s", "Tomoe")
    locked = profiles.update(db, tomoe["id"], base_revision=0,
                             set_fields={"delivery.energy": "low"}, lock=["delivery.energy"])
    lines = [{"revision_id": "rev-1", "cue": f"c{i}", "start": i * 3.0, "end": i * 3.0 + 2.0,
              "band": "intense" if i < 6 else "calm", "relative_db": 5.0 if i < 6 else 0.0,
              "pitch_hz": 200.0 + i} for i in range(12)]
    proposals = profiles.proposals_from_lines(lines)
    ids = [p["id"] for p in proposals]
    assert "delivery.energy" in ids and "vocal.pitch_range" in ids
    after = profiles.apply_proposals(db, tomoe["id"], proposals, ids,
                                     base_revision=locked["revision"])
    assert after["delivery"]["energy"] == "low"
    assert "delivery.energy" in after["skipped_locked"]
    assert after["vocal"]["pitch_range"]["low"] is not None
    refs = after["references"]
    assert refs and all(r["approved"] for r in refs)
    assert {r["kind"] for r in refs} == {"neutral", "expressive"}
    # Approving the same reference again adds nothing.
    again = profiles.apply_proposals(db, tomoe["id"], proposals, ids,
                                     base_revision=after["revision"])
    assert len(again["references"]) == len(refs)


def test_references_record_variation_coverage_and_review(db):
    kaito = identity.ensure_character(db, "s", "Kaito")
    p = profiles.add_reference(db, kaito["id"], {
        "kind": "expressive", "variation": "shout",
        "source": {"revision_id": "rev-1", "start": 1.0, "end": 3.5, "cue": "c1"},
        "transcript": "Get down!"}, base_revision=0)
    assert profiles.coverage(p)["approved"] == 0      # added is not approved
    rid = p["references"][0]["id"]
    p = profiles.review_reference(db, kaito["id"], rid, approved=True,
                                  base_revision=p["revision"])
    cover = profiles.coverage(p)
    assert cover["expressive"] and not cover["neutral"]
    with pytest.raises(ValueError):
        profiles.add_reference(db, kaito["id"], {"variation": "singing", "source": {
            "start": 0, "end": 1}}, base_revision=p["revision"])


def test_one_character_can_have_a_voice_per_locale_and_one_voice_many_characters(db):
    series = "series:77"
    for character, voice, locale in (("Kaito", "v-kaito-mx", "es-MX"),
                                     ("Kaito", "v-kaito-es", "es-ES"),
                                     ("Kaito", "v-kaito-any", ""),
                                     ("Mina", "v-shared", ""), ("Ren", "v-shared", "")):
        casting.decide(db, casting.ChoiceIn(character=character, scope="series",
                                            scope_ref=series, voice=voice, locale=locale))
    choices = records.get(db, "casting", casting.record_id("series", series))["characters"]
    assert casting.pick(choices, "Kaito", locale="es-MX")["voice"] == "v-kaito-mx"
    assert casting.pick(choices, "Kaito", locale="es-AR")["voice"] == "v-kaito-any"
    assert casting.pick(choices, "Mina", locale="es-MX")["voice"] == "v-shared"
    assert casting.pick(choices, "Ren")["voice"] == "v-shared"
    rows = casting.effective(db, series_ref=series, episode_ref="e1",
                             speakers=["Kaito"], locale="es-ES")["speakers"]
    assert rows[0]["voice"] == "v-kaito-es"


def test_legacy_trait_writes_merge_instead_of_erasing(client_factory):
    client = client_factory()
    db = client.app.state.jobs.db
    calls = []
    client.app.state.services._cache["speech"] = SimpleNamespace(
        voice_profiles=lambda: [{"id": "p1", "name": "Kaito clone"}], preset_engines=(),
        preset_voices=lambda e: [], generate=lambda *a, **k: calls.append(a))
    db.save_plan("voice-traits:profile:p1", "Voice traits",
                 {"display_name": "Kaito", "future_field": "kept"})
    client.put("/api/voice-catalog/traits", json={"key": "profile:p1", "color": "#112233"})
    saved = db.load_plan("voice-traits:profile:p1")["plan"]
    assert saved["future_field"] == "kept" and saved["display_name"] == "Kaito"
    assert saved["color"] == "#112233"
    assert calls == []           # saving a colour never asks for speech


def test_profile_routes_read_and_save_without_any_speech(client_factory):
    client = client_factory()
    calls = []

    class Speech:
        def supports_direction(self, engine):
            return engine == "qwen"

        def supports_cloning(self, engine):
            return True

        def generate(self, *a, **k):
            calls.append(a)

        def clone_voice(self, *a, **k):
            calls.append(a)

    client.app.state.services._cache["speech"] = Speech()
    made = client.post("/api/characters", json={"series_id": "show:tvdb:9",
                                                "name": "Kaito"}).json()
    cid = made["id"]
    view = client.get(f"/api/characters/{cid}/profile").json()
    assert view["profile"]["revision"] == 0
    saved = client.patch(f"/api/characters/{cid}/profile", json={
        "base_revision": 0, "set": {"delivery.pace": "slow"}, "lock": ["delivery.pace"]})
    assert saved.status_code == 200
    stale = client.patch(f"/api/characters/{cid}/profile", json={
        "base_revision": 0, "set": {"delivery.pace": "quick"}})
    assert stale.status_code == 409
    put = client.put(f"/api/characters/{cid}/assignments", json={
        "voice": "profile:p1", "engine": "qwen", "locale": "es-MX"}).json()
    row = put["assignments"][0]
    assert row["locale"] == "es-MX" and row["capabilities"]["direction"] is True
    assert row["variations"]["whisper"] == "yes"
    listed = client.get("/api/characters", params={"series_id": "show:tvdb:9"}).json()
    assert listed["characters"][0]["assignments"] == 1
    assert calls == []


def test_a_dub_run_inherits_voices_of_characters_identified_by_analysis(db, tmp_path):
    import json

    from doblarr import snapshots, voices

    script = tmp_path / "e.script.json"
    script.write_text(json.dumps({"segments": [
        {"speaker": "SPEAKER_00", "start": 0, "end": 2, "cue": {"cue_id": "c0"}},
        {"speaker": "SPEAKER_01", "start": 3, "end": 5, "cue": {"cue_id": "c1"}}]}),
        encoding="utf-8")
    snapshots.record_stage(db, "rev-9", "ja", "transcribe", "done", inputs=[1],
                           outputs={"script": str(script)})
    kaito = identity.ensure_character(db, "show:tvdb:5", "Kaito")
    identity.associate(db, "rev-9", "cluster", "SPEAKER_00", kaito["id"], state="manual")
    casting.decide(db, casting.ChoiceIn(character="Kaito", scope="series",
                                        scope_ref="series:5", voice="v-kaito",
                                        locale="es-MX", pitch_semitones=2))
    # The dub run grouped the same cues under other labels.
    job = SimpleNamespace(target_locale="es-MX", segments=[
        Segment(0, 0, 2, "a", speaker="SPEAKER_07", cue_id="c0"),
        Segment(1, 3, 5, "b", speaker="SPEAKER_02", cue_id="c1")])
    cast = voices.assigned_cast(job, db, "rev-9", "show:tvdb:5")
    assert [(e["speaker_id"], e["voice"], e.get("pitch_semitones")) for e in cast] == [
        ("SPEAKER_07", "v-kaito", 2)]


def test_characters_list_across_shows_and_where_each_one_talks(client_factory, tmp_path):
    import json

    from doblarr import snapshots

    client = client_factory()
    db = client.app.state.jobs.db
    episode = tmp_path / "harbor-e02.mkv"
    episode.write_bytes(b"")
    script = tmp_path / "e.script.json"
    script.write_text(json.dumps({"identity": {"input": str(episode)}, "segments": [
        {"speaker": "SPEAKER_00", "start": 4.0, "end": 6.0, "text_src": "Wait for me!",
         "cue": {"cue_id": "c0"}},
        {"speaker": "SPEAKER_01", "start": 7.0, "end": 8.0, "text_src": "Huh?",
         "cue": {"cue_id": "c1"}},
        {"speaker": "SPEAKER_00", "start": 1.0, "end": 2.5, "text_src": "Morning.",
         "cue": {"cue_id": "c2"}}]}), encoding="utf-8")
    snapshots.record_stage(db, "rev-7", "ja", "transcribe", "done", inputs=[1],
                           outputs={"script": str(script)})
    kaito = identity.ensure_character(db, "show:tvdb:9", "Kaito")
    identity.ensure_character(db, "movie:tmdb:4", "Ren")
    identity.associate(db, "rev-7", "cluster", "SPEAKER_00", kaito["id"], state="manual")
    client.put(f"/api/characters/{kaito['id']}/assignments", json={"voice": "vb-k"})
    listed = client.get("/api/characters").json()["characters"]
    assert {c["name"] for c in listed} == {"Kaito", "Ren"}
    assert next(c for c in listed if c["name"] == "Kaito")["voices"] == ["vb-k"]
    talks = client.get(f"/api/characters/{kaito['id']}/appearances").json()
    assert talks["lines"] == 2
    [found] = talks["episodes"]
    assert found["episode"] == "harbor-e02" and found["reachable"] is True
    assert [line["text"] for line in found["lines"]] == ["Morning.", "Wait for me!"]

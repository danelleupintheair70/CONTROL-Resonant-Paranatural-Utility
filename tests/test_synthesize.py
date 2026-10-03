

def test_a_voice_with_no_sample_borrows_the_voice_it_sounds_most_like(tmp_path):
    import json
    from types import SimpleNamespace

    from doblarr.models import Segment, Speaker
    from doblarr.stages import synthesize

    vocals = tmp_path / "e.vocals.wav"
    vocals.write_bytes(b"")
    (tmp_path / "e.speakers.json").write_text(json.dumps({"lines": [
        {"speaker": "V0", "vector": [1, 0, 0]}, {"speaker": "V1", "vector": [0, 1, 0]},
        {"speaker": "V9", "vector": [0.1, 0.95, 0]}]}), encoding="utf-8")
    speakers = {label: Speaker(label=label) for label in ("V0", "V1", "V9")}
    speakers["V0"].voicebox_profile_id, speakers["V1"].voicebox_profile_id = "kaito", "mina"
    job = SimpleNamespace(speakers=speakers, vocals=vocals, input_file=tmp_path / "e.mkv",
                          kind="full", metrics={},
                          segments=[Segment(0, 0.0, 2.0, "a", speaker="V0")])
    synthesize._borrow_voices(job, [speakers["V9"]])
    assert speakers["V9"].voicebox_profile_id == "mina"
    assert job.metrics["voices_borrowed"]["V9"]["from"] == "V1"

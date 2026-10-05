

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


def test_a_short_line_trailing_off_is_spoken_with_a_period_on_chatterbox():
    from doblarr.stages.quality import engine_safe

    assert engine_safe("Escuadrón Cinco...", "chatterbox") == "Escuadrón Cinco."
    assert engine_safe("Bien… ", "chatterbox") == "Bien."
    assert engine_safe("¿Y tú...?", "chatterbox") == "¿Y tú...?"          # a question stays
    assert engine_safe("Teníamos a Ren con nosotros...", "chatterbox").endswith("...")
    assert engine_safe("Escuadrón Cinco...", "qwen") == "Escuadrón Cinco..."


def test_chatterbox_sampling_comes_from_config_then_the_cast_and_reruns_on_change(tmp_path):
    from doblarr.models import DubJob, Segment, Speaker
    from doblarr.stages import synthesize

    src = tmp_path / "e.mkv"
    src.write_text("video", encoding="utf-8")
    job = DubJob(input_file=src, source_lang="ja", target_lang="es")
    job.source_audio = tmp_path / "source.wav"
    job.speakers = {label: Speaker(label, voicebox_profile_id=label.lower())
                    for label in ("KAITO", "MINA", "BELL")}
    job.segments = [Segment(0, 0.0, 1.0, "hola", speaker="KAITO"),
                    Segment(1, 1.0, 2.0, "adiós", speaker="MINA"),
                    Segment(2, 2.0, 3.0, "ding", speaker="BELL")]
    calls = {}

    class Voicebox:
        def supports_sampling(self, engine):
            return engine == "chatterbox"

        def synthesize_to_file(self, profile, text, lang, dest, **kwargs):
            calls[profile] = kwargs.get("sampling")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(text.encode())

    cast = {"MINA": {"exaggeration": 0.9}, "BELL": {"engine": "kokoro"}}
    defaults = {"exaggeration": 0.6, "cfg_weight": 0.0, "temperature": None}
    synthesize.run(job, Voicebox(), tmp_path / "work", cast=cast, engine="chatterbox",
                   sampling=defaults)
    assert calls == {"kaito": {"exaggeration": 0.6, "cfg_weight": 0.0},
                     "mina": {"exaggeration": 0.9, "cfg_weight": 0.0},
                     "bell": None}

    calls.clear()
    synthesize.run(job, Voicebox(), tmp_path / "work", cast=cast, engine="chatterbox",
                   sampling=defaults)
    assert calls == {}  # unchanged settings reuse every take
    synthesize.run(job, Voicebox(), tmp_path / "work", cast=cast, engine="chatterbox",
                   sampling={**defaults, "cfg_weight": 0.3})
    assert set(calls) == {"kaito", "mina"}  # the kokoro line never used sampling

"""How a line is said: the picture's reading, checked against the voice."""

from doblarr import emotion


def seen(feeling, confidence="high", face=True):
    return {"face_visible": face, "speaker_on_screen": True, "expression": "mouth open",
            "feeling": feeling, "intensity": 0.8, "confidence": confidence}


def test_the_face_decides_and_the_voice_says_whether_it_agrees():
    assert emotion.fuse({"feeling": "happy", "score": 0.8}, seen("excited")) == {
        "feeling": "excited", "intensity": 0.8, "confidence": "high", "agree": True,
        "from": "picture", "hints": {"voice": "happy", "words": ""}}
    disagree = emotion.fuse({"feeling": "sad", "score": 0.9}, seen("happy"))
    assert disagree["feeling"] == "happy" and disagree["agree"] is False
    assert disagree["confidence"] == "low"
    assert emotion.fuse(None, seen("angry"))["confidence"] == "medium"


def test_without_a_face_a_line_stays_unknown_with_the_other_readings_as_hints():
    found = emotion.fuse({"feeling": "afraid", "score": 0.9}, seen("sad", "low", face=False))
    assert found["feeling"] == "" and found["confidence"] == "none"
    assert found["hints"] == {"voice": "afraid", "words": "sad"}
    assert emotion.fuse(None, None)["feeling"] == ""


def test_the_script_reader_tallies_what_it_says_about_each_voice():
    from doblarr import dialogue_reader

    calls = [{"speaker": "Ren", "confidence": "high"}, {"speaker": "Ren", "confidence": "medium"},
             {"speaker": "Kaito", "confidence": "low"}, {"speaker": "", "confidence": "low"}]
    found = dialogue_reader.by_voice(["V1", "V1", "V1", "V2"], calls)
    assert found["V1"]["leading"] == "Ren" and found["V1"]["share"] == 0.86
    assert "V2" not in found
    assert dialogue_reader.windows(70) == [(0, 30), (22, 52), (44, 70)]


def test_a_face_that_is_not_the_speakers_gives_no_feeling():
    other = {**seen("smug"), "speaker_on_screen": False}
    assert emotion.fuse(None, other)["feeling"] == ""

"""Who the dialogue says each voice is: names answered to, names called."""

from doblarr import dialogue_clues


def line(speaker, start, text, cue=None):
    return {"speaker": speaker, "start": start, "end": start + 1.5, "text": text,
            "cue": cue or f"c{start}"}


SCENE = [
    line("V1", 0, "What is it, Ren?"),
    line("V2", 2, "Have you heard the rumour about the harbour?"),
    line("V1", 4, "Go on."),
    line("V3", 6, "Ren-sama! The guards are ready."),
    line("V2", 8, "Good. Wait for my signal."),
    line("V1", 10, "Well done, Ren."),
    line("V2", 12, "Thank you, Kaito-sensei."),
    line("V1", 30, "Kaito!"),                   # nobody answers within the gap
]


def test_a_voice_is_suggested_by_the_name_it_answers_to_not_one_it_calls():
    found = dialogue_clues.read(SCENE, cast=["Kaito", "Mina"])["groups"]
    assert found["V2"]["suggests"] == "Ren"
    assert found["V2"]["answers"][0] == {"name": "Ren", "count": 3, "cues": ["c2", "c8", "c12"]}
    assert {c["name"] for c in found["V2"]["calls"]} == {"Kaito"}
    assert found["V1"]["suggests"] == ""          # it calls Ren and Kaito, answers nobody
    assert found["V3"]["suggests"] == ""          # one call heard, no answers


def test_words_and_ranks_are_not_taken_for_names():
    lines = [line("V1", 0, "Captain! The Captain is here."), line("V2", 2, "Hello."),
             line("V1", 4, "Captain, listen."), line("V2", 6, "Okay! hello again.")]
    names = dialogue_clues.candidates(lines, cast=["MINA"])
    assert names == {"mina": "MINA"}               # cast spelling kept, ranks and words out


def test_a_name_used_once_and_not_in_the_cast_is_not_a_candidate():
    lines = [line("V1", 0, "Sora!"), line("V2", 2, "Yes?")]
    assert dialogue_clues.read(lines)["groups"]["V2"]["answers"] == []

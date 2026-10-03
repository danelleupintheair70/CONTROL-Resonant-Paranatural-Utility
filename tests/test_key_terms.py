"""The names and terms an episode keeps saying, and whether the dub keeps them."""

from types import SimpleNamespace

from doblarr import key_terms
from doblarr.models import Segment

SOURCE = [
    "Mira-sensei, the Lantern Exam starts today!",
    "Well, the harbor has been quiet.",
    "The Lantern Exam is no joke, Kaito.",
    "Everyone in the Harbor trusts the Guild.",
    "The Harbor Guild sent a message to the harbor.",
    "Okay. Meet me at the Third Lantern Docks.",
    "This was your first Lantern Dock, wasn't it?",
    "Mira-sensei is late again.",
    "Heh. The Guild never waits.",
]
OURS = [
    "¡Mira-sensei, hoy empieza el Examen Linterna!",
    "Bueno, el puerto ha estado tranquilo.",
    "El Examen Linterna no es broma, Kaito.",
    "Todos en el Puerto confían en el Gremio.",
    "El Gremio del Puerto mandó un mensaje a la bahía.",
    "Bien. Nos vemos en los Muelles de la Linterna Tres.",
    "Este fue tu primer Embarcadero Linterna, ¿verdad?",
    "La sensei Mira llega tarde otra vez.",
    "Je. El Gremio nunca espera.",
]


def test_terms_are_repeated_proper_phrases_not_sentence_starts():
    found = {t["term"]: t["lines"] for t in key_terms.find(SOURCE)}
    assert found["Lantern Exam"] == [0, 2]
    assert found["Mira-sensei"] == [0, 7]
    assert found["Guild"] == [3, 4, 8]
    # "Harbor" counts its lowercase uses: the harbor is the Harbor.
    assert found["Harbor"] == [1, 3, 4]
    # Two docks phrases share a term; plurals are one term.
    assert found["Lantern Dock"] == [5, 6]
    for filler in ("Well", "Okay", "Heh", "The", "Everyone"):
        assert filler not in found


def test_read_back_finds_the_rendering_and_the_lines_that_drift():
    found = {t["term"]: t["lines"] for t in key_terms.find(SOURCE)}
    harbor = key_terms.read_back("Harbor", found["Harbor"], OURS)
    assert harbor["rendering"] == "puerto"
    assert harbor["missing"] == [] and harbor["share"] == 1.0
    # A name kept as it is reads back as itself, honorific order aside.
    assert key_terms.read_back("Mira-sensei", found["Mira-sensei"], OURS)["share"] == 1.0
    # One word read back for a two-word term: the wordings around it differ.
    docks = key_terms.read_back("Lantern Dock", found["Lantern Dock"], OURS)
    assert docks["share"] == 0.5
    assert len(docks["variants"]) == 1


def test_matching_ignores_case_accents_plurals_and_articles():
    assert key_terms.says("las ensenadas ocultas del Faro", "la Ensenada Oculta del Faro")
    assert key_terms.says("¿Y el EXÁMEN?", "examen")
    assert not key_terms.says("el puerto", "la bahía")


def _job(source, translated):
    segments = []
    for n, (src, out) in enumerate(zip(source, translated, strict=True)):
        seg = Segment(n, n * 3.0, n * 3.0 + 2.0, src, cue_id=f"c{n}")
        seg.text_translated = out
        segments.append(seg)
    return SimpleNamespace(segments=segments, target_locale="es-419", target_lang="es",
                           metrics={})


class Reviser:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def revise(self, text, language, instruction, target_chars=None):
        self.asked.append(instruction)
        return self.answer(text)


def test_a_glossary_term_said_another_way_is_rewritten():
    job = _job(SOURCE, OURS[:4] + ["El Gremio de la Bahía mandó un mensaje."] + OURS[5:])
    reviser = Reviser(lambda text: text.replace("de la Bahía", "del Puerto"))
    counts = key_terms.enforce(job, reviser, {"Harbor Guild": "el Gremio del Puerto"})
    assert counts["revised"] == 1 and counts["open"] == 0
    assert job.segments[4].text_translated == "El Gremio del Puerto mandó un mensaje."
    assert '"Harbor Guild" must be "el Gremio del Puerto"' in reviser.asked[0]


def test_a_rewrite_that_still_misses_the_term_keeps_a_finding():
    job = _job(SOURCE, OURS[:4] + ["El Gremio de la Bahía mandó un mensaje."] + OURS[5:])
    counts = key_terms.enforce(job, Reviser(lambda text: "Otra cosa."),
                               {"Harbor Guild": "el Gremio del Puerto"})
    assert counts["open"] == 1
    finding = [f for f in job.segments[4].findings if f.detector == key_terms.DETECTOR]
    assert finding and finding[0].code == key_terms.CODE
    assert job.segments[4].text_translated.startswith("El Gremio de la Bahía")


def test_a_capitalised_glossary_source_leaves_the_common_word_alone():
    job = _job(["Will is here.", "I will go."], ["Will está aquí.", "Iré."])
    assert key_terms.enforce(job, None, {"Will": "Will"})["open"] == 0


def test_the_majority_wording_holds_only_where_the_term_is_capitalised():
    source = ["The Harbor is calm.", "Back to the Harbor!", "From the Harbor, we sail.",
              "He was harboring a grudge."]
    ours = ["El Puerto está en calma.", "¡De vuelta al Puerto!", "Desde la Bahía zarpamos.",
            "Guardaba rencor."]
    hold = key_terms.to_hold(source, ours, {})
    assert hold == [{"source": "Harbor", "rendering": "Puerto", "proper": True}]
    job = _job(source, ours)
    assert key_terms.enforce(job, None, {})["open"] == 1  # the Bahía line, not the verb


def test_the_official_dub_is_read_the_same_way():
    found = {t["term"]: t for t in key_terms.find(SOURCE)}
    dub = ["", "El muelle está en calma.", "", "Todos en el muelle confían en el Gremio.",
           "El Gremio del muelle avisó al muelle.", "", "", "", ""]
    rows = {r["term"]: r for r in key_terms.episode(SOURCE, OURS, dub=dub)}
    assert rows["Harbor"]["dub"]["rendering"] == "muelle"
    assert rows["Harbor"]["kind"] == "term"
    assert rows["Mira-sensei"]["kind"] == "name"
    assert found["Harbor"]["lines"] == rows["Harbor"]["lines"]

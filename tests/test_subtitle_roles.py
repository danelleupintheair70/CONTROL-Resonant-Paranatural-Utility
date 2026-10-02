"""What kind of line each subtitle is, from the track's own styles."""

from doblarr import subtitle_roles

STYLE = (",Arial,30,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,"
         "10,10,10,1")
FIELDS = ("Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
          "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
          "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
EVENTS = [
    ("0:00:01.00", "0:00:03.00", "Default", "Wait for me, Mina!"),
    ("0:00:04.00", "0:00:06.00", "Default", r"{\i1}She never waits...{\i0}"),
    ("0:00:07.00", "0:00:09.00", "Lyrics ENG OP", "Sail across the harbor lights"),
    ("0:00:07.00", "0:00:09.00", "Signs", r"{\pos(300,100)}Harbor Gate"),
    ("0:00:20.00", "0:00:23.00", "NEP", "Next time, the storm arrives!"),
]
ASS = "\n".join([
    "[Script Info]", "ScriptType: v4.00+", "", "[V4+ Styles]", f"Format: {FIELDS}",
    *(f"Style: {name}{STYLE}" for name in ("Default", "Lyrics ENG OP", "Signs", "NEP")), "",
    "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    *(f"Dialogue: 0,{a},{b},{style},,0,0,0,,{text}" for a, b, style, text in EVENTS), ""])


def test_styles_and_italics_say_what_each_line_is(tmp_path):
    path = tmp_path / "e.styles.ass"
    path.write_text(ASS, encoding="utf-8")
    found = subtitle_roles.events(path)
    assert [e["role"] for e in found] == ["dialogue", "inner", "song", "onscreen", "preview"]
    lines = [{"cue": "a", "start": 1.0, "end": 3.0}, {"cue": "b", "start": 4.0, "end": 6.0},
             {"cue": "c", "start": 20.0, "end": 23.0}]
    roles = subtitle_roles.annotate(lines, found)
    assert {k: v["role"] for k, v in roles.items()} == {"a": "dialogue", "b": "inner",
                                                         "c": "preview"}
    assert subtitle_roles.on_screen(found) == [
        {"start": 7.0, "end": 9.0, "text": "Harbor Gate", "kind": "sign"}]


def test_a_video_without_a_styled_track_gives_plain_dialogue(tmp_path):
    script = tmp_path / "e.script.json"
    assert subtitle_roles.ensure_styled(script, tmp_path / "missing.mkv", "en") is None
    assert subtitle_roles.style_role("Default") == "dialogue"
    assert subtitle_roles.style_role("Narrator") == "narration"

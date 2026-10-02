"""The questions worth asking about an episode's voices."""

from doblarr import doubts


def line(i, speaker, start, length=2.0, method="clustered", margin=0.4, top=0.8, locked=False):
    return {"index": i, "cue": f"c{i}", "speaker": speaker, "start": start, "end": start + length,
            "text": f"line {i}", "locked": locked, "features": {"quality": "ok"},
            "why": {"method": method, "margin": margin,
                    "candidates": [{"label": speaker, "similarity": top},
                                   {"label": "V1", "similarity": top - (margin or 0)}]}}


def test_unnamed_voices_come_first_then_the_lines_decided_on_little_evidence():
    lines = [line(0, "V1", 0), line(1, "V1", 3), line(2, "V1", 6),
             line(3, "V2", 9, 4.0), line(4, "V2", 14, 4.0), line(5, "V2", 19, 4.0),
             line(6, "V1", 24, 0.6, method="nearest", margin=0.02, top=0.4),
             line(7, "V1", 26, 0.6, method="nearest", margin=0.02, top=0.4, locked=True)]
    asks = doubts.queue(lines, {"V1": "Kaito"},
                        dialogue={"V2": {"answers": [{"name": "Mina", "count": 2}]}})
    assert [a["kind"] for a in asks] == ["voice", "line"]
    assert asks[0]["voice"] == "V2" and asks[0]["lines"] == 3
    assert asks[0]["hints"][0]["name"] == "Mina"
    assert asks[1]["line"]["cue"] == "c6" and asks[1]["now"] == "Kaito"   # c7 was answered
    assert "joined the closest voice" in " ".join(asks[1]["reasons"])

"""Japanese names respelled for a Spanish engine, and only those listed."""

from doblarr.romaji import respell, respellings


def test_the_letters_spanish_misreads_are_respelled_as_latino_dubs_say_them():
    assert respell("Jiro") == "Yiro"
    assert respell("jinja") == "yinya"
    assert respell("Hikari") == "Jikari"
    assert respell("Kagerou") == "Kaguerou"
    assert respell("Gin") == "Guin"


def test_digraphs_and_names_spanish_already_reads_well_are_left_alone():
    for name in ("Shiori", "Chika", "Mina", "Ren", "Tomoe", "Sora"):
        assert respell(name) == name


def test_only_terms_that_change_are_returned():
    assert respellings(["Kaito", "Hikari", "", None]) == {"Hikari": "Jikari"}

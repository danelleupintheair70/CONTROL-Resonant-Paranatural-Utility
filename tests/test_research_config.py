"""Title research settings and the Prompture it needs."""

import copy
import importlib.util

import pytest

from doblarr.config import DEFAULTS, Config
from doblarr.config_schema import ConfigModel


def test_research_is_off_by_default_and_cheap():
    research = DEFAULTS["research"]
    assert research["enabled"] is False
    assert research["depth"] == "quick"
    assert research["max_cost_usd"] == 1.0
    assert research["model"] == ""


def test_research_keys_never_reach_the_browser():
    data = copy.deepcopy(DEFAULTS)
    data["research"].update(opensubtitles_api_key="os-key", tmdb_api_key="tmdb-key")
    shown = Config(data).as_dict(redact_secrets=True)["research"]
    assert "os-key" not in shown.values() and "tmdb-key" not in shown.values()


def test_a_bad_depth_is_reported(caplog):
    data = copy.deepcopy(DEFAULTS)
    data["research"]["depth"] = "bottomless"
    from doblarr.config_schema import validate_config

    validate_config(data)
    assert "research.depth" in caplog.text
    assert ConfigModel.model_validate(DEFAULTS).research.depth == "quick"


@pytest.mark.skipif(importlib.util.find_spec("prompture") is None, reason="prompture not installed")
def test_prompture_has_the_anilist_reader():
    from prompture.tools.web import search_anilist

    assert callable(search_anilist)

"""Isolated browser-test server: temporary data and a fake media library."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

from doblarr.config import Config
from doblarr.server import create_app

_temp = tempfile.TemporaryDirectory(prefix="doblarr-browser-")
_root = Path(_temp.name)
config = Config.load(_root / "config.yaml")
config.apply_and_save({
    "paths": {"work_dir": str(_root / "work"), "output_dir": str(_root / "output")},
    "knowledge": {"auto_install_starter": False},
})
app = create_app(config)
services = app.state.services
FAKES = {
    "radarr": SimpleNamespace(list_movies=lambda: [{
        "title": "Test Film", "year": 2024, "hasFile": True, "tmdbId": 42,
        "originalLanguage": {"name": "Korean"},
        "movieFile": {"path": str(_root / "film.mkv"),
                      "mediaInfo": {"audioLanguages": "kor"}},
    }]),
    "speech": SimpleNamespace(list_voices=lambda: [], voice_profiles=lambda: []),
}


def _install_fakes():
    services._cache.update(FAKES)


# Saving settings invalidates the client cache; without this a spec that runs
# after a settings save would reach for a real Radarr or voice service.
_invalidate = services.invalidate
services.invalidate = lambda: (_invalidate(), _install_fakes())
_install_fakes()

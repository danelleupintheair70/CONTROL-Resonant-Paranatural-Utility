"""The speech-service contract Doblarr drives, and the factory that picks one.

Doblarr never loads a TTS model itself: it clones voices, generates lines and
checks them by ear through one speech service over HTTP. Two services speak the
contract — voicebox and VoiceStudio — and `speech.backend` chooses between
them. Callers depend on `SpeechClient` only. Each adapter owns its service's
endpoints, payload shapes and engine names, and answers what its engines can
do (`supports_direction`, `supports_cloning`) so the pipeline never guesses.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ArrClientError
from .base import ArrClient

BACKENDS = ("voicebox", "voicestudio")


class SpeechError(ArrClientError, RuntimeError):
    """The speech service failed or refused a request."""


class GenerationFailed(SpeechError):
    """A confirmed terminal failure; safe to submit a new generation."""


class Unsupported(SpeechError):
    """The configured speech service does not offer this operation."""


class SpeechClient(ArrClient):
    """What Doblarr needs from a speech service.

    Voices are addressed by the service's own profile id. A clone is created
    with its reference sample in one call (`clone_voice`), because a profile
    without a sample is useless and some services cannot hold one.
    """

    service = "speech"
    error_cls: type[SpeechError] = SpeechError
    # Engines whose curated preset voices the voice catalog lists.
    preset_engines: tuple[str, ...] = ()

    def __init__(self, base_url: str, timeout: int = 600, headers: dict | None = None):
        super().__init__(base_url, timeout=timeout, headers=headers)
        self.observer = None

    def observe(self, name, value=1):
        if self.observer:
            self.observer(name, value)

    def fork(self) -> SpeechClient:
        """A client for the same service with its own HTTP session (one per worker thread)."""
        raise NotImplementedError

    # -- engines ----------------------------------------------------------
    def canonical_engine(self, engine: str) -> str:
        return str(engine or "")

    def supports_direction(self, engine: str) -> bool:
        """Whether `engine` can be given a delivery instruction at all."""
        return False

    def supports_sampling(self, engine: str) -> bool:
        """Whether `engine` takes exaggeration / cfg_weight / temperature overrides."""
        return False

    def supports_cloning(self, engine: str) -> bool | None:
        """Whether `engine` clones from a reference; None when the service cannot say."""
        return None

    # -- service ----------------------------------------------------------
    def health(self, timeout: int = 15) -> dict:
        raise NotImplementedError

    def llm_generate(self, prompt: str, system: str | None = None, **options) -> str:
        raise Unsupported(f"{self.service} offers no language model; "
                          "choose another translate.provider")

    def transcribe(self, audio: Path, language: str | None = None) -> dict:
        raise NotImplementedError

    # -- voices -----------------------------------------------------------
    def voice_profiles(self) -> list[dict]:
        raise NotImplementedError

    def list_voices(self) -> list[dict]:
        """Available voices as [{id, name}]."""
        return [
            {"id": p.get("id") or p.get("profile_id"), "name": p.get("name", "?")}
            for p in self.voice_profiles()
        ]

    def preset_voices(self, engine: str) -> list[dict]:
        return []

    def register_preset(self, voice: dict, engine: str) -> str:
        raise Unsupported(f"{self.service} has no preset voices to register")

    def clone_voice(self, name: str, language: str, sample: Path, reference_text: str,
                    description: str = "") -> str:
        """Create a cloned voice from one reference sample; return its profile id."""
        raise NotImplementedError

    def delete_profile(self, profile_id: str) -> None:
        self._delete(f"/profiles/{profile_id}")

    # -- generation -------------------------------------------------------
    def generate(self, profile_id: str, text: str, language: str, seed: int | None = None,
                 model_size: str | None = None, engine: str | None = None,
                 instruct: str | None = None, sampling: dict | None = None) -> str:
        """Start one generation; return an id for `generation_status`/`fetch_audio`."""
        raise NotImplementedError

    def generation_status(self, generation_id: str) -> dict:
        """{"status": ..., "error": ...} for a generation started by `generate`."""
        raise NotImplementedError

    def fetch_audio(self, generation_id: str) -> bytes:
        raise NotImplementedError

    def synthesize_to_file(self, profile_id: str, text: str, language: str, dest: Path,
                           cancel_event=None, **kwargs) -> Path:
        """Generate one line and write it to `dest`, blocking until it exists."""
        raise NotImplementedError

    def _check_direction(self, engine: str | None, instruct: str | None) -> None:
        if instruct and not self.supports_direction(engine or ""):
            raise self._error(
                f"{self.service} engine {engine or '(default)'} does not accept "
                "delivery instructions")


def build_speech_client(config) -> SpeechClient:
    """The client for the configured `speech.backend`."""
    from ..errors import ConfigError

    backend = (config.get("speech") or {}).get("backend", "voicebox")
    if backend == "voicebox":
        from .voicebox import VoiceboxClient

        vb = config["voicebox"]
        return VoiceboxClient(vb["base_url"], timeout=vb["timeout_seconds"])
    if backend == "voicestudio":
        from .voicestudio import VoiceStudioClient

        vs = config["voicestudio"]
        return VoiceStudioClient(vs["base_url"], timeout=vs["timeout_seconds"],
                                 api_key=vs.get("api_key") or None,
                                 directable_engines=vs.get("directable_engines") or ())
    raise ConfigError(f"speech.backend must be one of {', '.join(BACKENDS)}, not {backend!r}")

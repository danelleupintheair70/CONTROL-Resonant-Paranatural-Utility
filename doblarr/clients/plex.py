"""Minimal Plex client — enough to find items and manage labels.

Labels are added/removed non-destructively: `label[0].tag.tag=X` adds X while
keeping every existing label (Kometa's included), and `label[].tag.tag-=X` removes
just X. `label.locked=1` keeps the label through metadata refreshes.

The token travels in the `X-Plex-Token` header, not the query string, so it
stays out of URLs (and any logs that record them).
"""

from __future__ import annotations

from ..errors import ArrClientError
from .base import ArrClient

TYPE_NUM = {"movie": 1, "show": 2}


class PlexError(ArrClientError, RuntimeError):
    pass


class PlexClient(ArrClient):
    service = "Plex"
    auth_label = "token"
    error_cls = PlexError

    def __init__(self, base_url: str, token: str, timeout: int = 30):
        super().__init__(base_url, timeout=timeout,
                         headers={"X-Plex-Token": token,
                                  "Accept": "application/json"})
        self.token = token

    def sections(self) -> list[dict]:
        data = self._get("/library/sections")
        return [{"key": s["key"], "type": s["type"], "title": s["title"]}
                for s in data["MediaContainer"].get("Directory", [])]

    # -- library reading (Plex as a discovery source) ---------------------
    def section_items(self, section_key: str) -> list[dict]:
        """Every movie or show in a section, with its external ids."""
        data = self._get(f"/library/sections/{section_key}/all", {"includeGuids": 1},
                         timeout=120)
        return data["MediaContainer"].get("Metadata", [])

    def leaves(self, rating_key: str) -> list[dict]:
        """A show's episodes (or a movie itself), each with its file."""
        data = self._get(f"/library/metadata/{rating_key}/allLeaves", timeout=60)
        return data["MediaContainer"].get("Metadata", [])

    def metadata(self, rating_key: str) -> dict:
        """One item's full metadata, including every stream of every part."""
        data = self._get(f"/library/metadata/{rating_key}")
        found = data["MediaContainer"].get("Metadata") or [{}]
        return found[0]

    def image(self, path: str) -> tuple[bytes, str]:
        """An artwork path (a poster) as bytes and its media type."""
        resp = self._request("GET", path, headers={"Accept": "image/*"})
        return resp.content, resp.headers.get("Content-Type", "image/jpeg")

    @staticmethod
    def external_ids(item: dict) -> dict[str, int]:
        """{'tvdb': 81234, 'tmdb': 40404} from an item's Guid list."""
        ids = {}
        for guid in item.get("Guid") or []:
            scheme, _, value = str(guid.get("id", "")).partition("://")
            if scheme in ("tvdb", "tmdb") and value.isdigit():
                ids[scheme] = int(value)
        return ids

    @staticmethod
    def audio_languages(item: dict) -> list[str]:
        """ISO 639-2 codes of every audio stream, in stream order; 'und' if untagged."""
        codes = []
        for media in item.get("Media") or []:
            for part in media.get("Part") or []:
                for stream in part.get("Stream") or []:
                    if stream.get("streamType") == 2:
                        codes.append(str(stream.get("languageCode") or "und").lower())
        return codes

    @staticmethod
    def _meta_labels(m: dict) -> list[str]:
        return [lbl["tag"] for lbl in m.get("Label", [])]

    def find(self, section_key: str, type_num: int, title: str,
             year: int | None) -> dict | None:
        """Best match by exact (case-insensitive) title, preferring the right year."""
        data = self._get(f"/library/sections/{section_key}/all",
                         {"type": type_num, "title": title})
        cands = data["MediaContainer"].get("Metadata", [])
        exact = [m for m in cands if m.get("title", "").strip().lower() == title.strip().lower()]
        pool = exact or cands
        pick = None
        if year is not None:
            pick = next((m for m in pool if m.get("year") == year), None)
        pick = pick or (pool[0] if pool else None)
        if not pick:
            return None
        return {"ratingKey": pick["ratingKey"], "title": pick.get("title"),
                "year": pick.get("year"), "labels": self._meta_labels(pick)}

    def items_with_label(self, section_key: str, type_num: int, label: str) -> list[dict]:
        data = self._get(f"/library/sections/{section_key}/all",
                         {"type": type_num, "label": label})
        return [{"ratingKey": m["ratingKey"], "title": m.get("title"),
                 "year": m.get("year")} for m in data["MediaContainer"].get("Metadata", [])]

    def add_label(self, section_key: str, type_num: int, rating_key: str, label: str) -> None:
        self._put(f"/library/sections/{section_key}/all", {
            "type": type_num, "id": rating_key,
            "label[0].tag.tag": label, "label.locked": 1,
        })

    def remove_label(self, section_key: str, type_num: int, rating_key: str, label: str) -> None:
        self._put(f"/library/sections/{section_key}/all", {
            "type": type_num, "id": rating_key,
            "label[].tag.tag-": label, "label.locked": 1,
        })

    def refresh_item(self, rating_key: str) -> None:
        """Refresh one item's metadata (picks up newly muxed audio tracks).

        Documented as PUT; older Plex versions only accept POST, so fall back.
        The response body is empty, hence `_request` instead of `_put`/`_post`.
        """
        path = f"/library/metadata/{rating_key}/refresh"
        try:
            self._request("PUT", path)
        except PlexError as exc:
            if exc.status in (404, 405):
                self._request("POST", path)
            else:
                raise

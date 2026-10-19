from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    commit: str = "development"
    built_at: str = "not-packaged"
    dirty: bool = True

    @property
    def source_id(self) -> str:
        return f"{self.commit}{'-dirty' if self.dirty else ''}"


def current_build_identity() -> BuildIdentity:
    if not getattr(sys, "frozen", False):
        return BuildIdentity()
    try:
        payload = json.loads(
            files("ytmusic_player").joinpath("build-info.json").read_text(encoding="utf-8")
        )
        return BuildIdentity(
            commit=str(payload["commit"]),
            built_at=str(payload["built_at"]),
            dirty=bool(payload["dirty"]),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return BuildIdentity(commit="unknown", built_at="unknown", dirty=True)

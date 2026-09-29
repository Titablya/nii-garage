from __future__ import annotations

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Connection configuration shared by local, test, and VPS deployments."""

    url: str
    echo: bool = False

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            url=getenv("DATABASE_URL", "sqlite:///./arena.db"),
            echo=getenv("DATABASE_ECHO", "false").lower() in {"1", "true", "yes"},
        )

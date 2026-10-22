"""Settings configuration. Gets loaded once on startup."""
import os
from pathlib import Path
from dataclasses import dataclass

from ..domain import llm

ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Settings:
    """Service configuration, read once at startup from environment variables.

    Frozen, so the configuration can't be changed while the service runs.

    Attributes:
        case_dir: Folder with the case's ``*.md`` files and ``suspects.json``.
        model: Which model the detective uses, ``"fake"`` or ``"claude"``.
        max_turns: Maximum model calls per agent turn.
    """
    case_dir: Path
    model: str      # "fake" or "claude"
    max_turns: int


def load_settings() -> Settings:
    """Builds the settings from environment variables and validates them.

    Reads:
        CASE_DIR: Path to the case folder. Defaults to ``<project>/case_files``.
        DETECTIVE_MODEL: ``"fake"`` (default) or ``"claude"``, case-insensitive.
        MAX_TURNS: Positive integer. Defaults to 8.

    Returns:
        The validated settings.

    Raises:
        ValueError: If any variable has an invalid value. Failing at startup
            means a misconfigured container crashes immediately instead of
            misbehaving later.
    """
    case_dir = Path(os.environ.get("CASE_DIR", default=ROOT / "case_files"))
    if not case_dir.exists():
        raise ValueError(
            f"Path {case_dir} could not be found. Make sure to set the correct path using -e CASE_DIR=<path>"
        )

    model = os.environ.get("DETECTIVE_MODEL", "fake").strip().lower()
    if model not in ("fake", "claude"):
        raise ValueError(f"DETECTIVE_MODEL {model} unknown. Must be 'fake' or 'claude'.")
    if model == "claude" and not llm.has_api_key():
        raise ValueError("DETECTIVE_MODEL=claude needs ANTHROPIC_API_KEY to be set")

    max_turns = int(os.environ.get("MAX_TURNS", 8))
    if max_turns < 1:
        raise ValueError(f"MAX_TURNS {max_turns} invalid. Must be positive integer.")
    return Settings(case_dir, model, max_turns)

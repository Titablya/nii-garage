"""Fail-fast loader for versioned golden negotiation dialogues."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .domain.golden_dialogue import GoldenCaseType, GoldenDialogueDefinition


DEFAULT_GOLDEN_DIALOGUES_PATH = Path(__file__).resolve().parent.parent / "golden_dialogues"


class GoldenDialogueConfigurationError(RuntimeError):
    """Raised when the golden corpus cannot form an unambiguous catalog."""


@dataclass(frozen=True)
class GoldenDialogueCatalog:
    _items: tuple[GoldenDialogueDefinition, ...]

    def list(self) -> tuple[GoldenDialogueDefinition, ...]:
        return self._items

    def for_scenario(self, scenario_version_id: str) -> tuple[GoldenDialogueDefinition, ...]:
        return tuple(item for item in self._items if item.scenario_version_id == scenario_version_id)

    def get(
        self, scenario_version_id: str, case_type: GoldenCaseType | str
    ) -> GoldenDialogueDefinition | None:
        normalized_case = case_type.value if isinstance(case_type, GoldenCaseType) else case_type
        return next(
            (
                item
                for item in self._items
                if item.scenario_version_id == scenario_version_id
                and item.case_type.value == normalized_case
            ),
            None,
        )


def _read_definition(payload: dict[str, Any], source: Path) -> GoldenDialogueDefinition:
    try:
        return GoldenDialogueDefinition.model_validate_json(json.dumps(payload, ensure_ascii=False))
    except ValidationError as error:
        raise GoldenDialogueConfigurationError(
            f"Invalid golden dialogue in '{source.name}': {error}"
        ) from error


def load_golden_dialogue_catalog(
    corpus_path: Path = DEFAULT_GOLDEN_DIALOGUES_PATH,
) -> GoldenDialogueCatalog:
    if not corpus_path.exists() or not corpus_path.is_dir():
        raise GoldenDialogueConfigurationError(
            f"Golden dialogue directory does not exist: '{corpus_path}'"
        )

    files = tuple(sorted(corpus_path.rglob("*.json")))
    if not files:
        raise GoldenDialogueConfigurationError(
            f"No golden dialogue JSON files found in '{corpus_path}'"
        )

    items: list[GoldenDialogueDefinition] = []
    sources_by_key: dict[tuple[str, GoldenCaseType], Path] = {}
    for source in files:
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise GoldenDialogueConfigurationError(
                f"Invalid JSON in '{source.name}': {error.msg}"
            ) from error
        except OSError as error:
            raise GoldenDialogueConfigurationError(
                f"Cannot read golden dialogue '{source}': {error}"
            ) from error

        if not isinstance(payload, dict):
            raise GoldenDialogueConfigurationError(
                f"Invalid golden dialogue in '{source.name}': root must be exactly one object"
            )
        definition = _read_definition(payload, source)
        key = (definition.scenario_version_id, definition.case_type)
        previous_source = sources_by_key.get(key)
        if previous_source is not None:
            raise GoldenDialogueConfigurationError(
                "Duplicate golden dialogue for "
                f"'{definition.scenario_version_id}/{definition.case_type.value}' "
                f"in '{previous_source.name}' and '{source.name}'"
            )
        sources_by_key[key] = source
        items.append(definition)

    return GoldenDialogueCatalog(tuple(items))


@lru_cache(maxsize=1)
def get_golden_dialogue_catalog() -> GoldenDialogueCatalog:
    return load_golden_dialogue_catalog()


def clear_golden_dialogue_catalog_cache() -> None:
    get_golden_dialogue_catalog.cache_clear()

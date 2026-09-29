"""Loading and public projection of published negotiation scenarios.

The catalog is deliberately the single boundary between the full scenario
configuration (which contains facilitator-only information) and the API.  No
caller outside this module needs to read a JSON scenario directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from threading import RLock

from .domain.scenario import ScenarioDefinition
from .models import Scenario
from .random_scenarios import build_random_scenarios, random_variant_metadata
from .tasking import participant_tasks


DEFAULT_SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "scenarios"


class ScenarioConfigurationError(RuntimeError):
    """Raised when published scenario files cannot safely form a catalog."""


@dataclass
class ScenarioCatalog:
    """An immutable, indexed collection of published scenario projections."""

    _items: tuple[Scenario, ...]
    _definitions: tuple[ScenarioDefinition, ...]
    _custom_items: dict[str, Scenario] = field(default_factory=dict, init=False, repr=False)
    _custom_definitions: dict[str, ScenarioDefinition] = field(default_factory=dict, init=False, repr=False)
    _custom_owners: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def list(self) -> tuple[Scenario, ...]:
        with self._lock:
            return (*self._items, *self._custom_items.values())

    def get(self, scenario_id: str) -> Scenario | None:
        with self._lock:
            return self._custom_items.get(scenario_id) or next((item for item in self._items if item.id == scenario_id), None)

    def get_definition(self, scenario_id: str) -> ScenarioDefinition | None:
        """Internal-only full definition; never return this from an API route."""
        with self._lock:
            return self._custom_definitions.get(scenario_id) or next((item for item in self._definitions if item.metadata.id == scenario_id), None)

    def register_custom(self, public: Scenario, definition: ScenarioDefinition, owner_id: str) -> None:
        if public.id != definition.metadata.id or public.source != "custom":
            raise ScenarioConfigurationError("Custom scenario identity is inconsistent")
        with self._lock:
            self._custom_items[public.id] = public
            self._custom_definitions[public.id] = definition
            self._custom_owners[public.id] = owner_id

    def custom_owner(self, scenario_id: str) -> str | None:
        with self._lock:
            return self._custom_owners.get(scenario_id)

    def remove_custom_for_user(self, owner_id: str) -> None:
        with self._lock:
            ids = [key for key, value in self._custom_owners.items() if value == owner_id]
            for scenario_id in ids:
                self._custom_items.pop(scenario_id, None)
                self._custom_definitions.pop(scenario_id, None)
                self._custom_owners.pop(scenario_id, None)


def _read_scenario_definition(payload: dict[str, Any], source: Path) -> ScenarioDefinition:
    """Validate a configuration before it can enter the runtime catalog."""
    try:
        # ScenarioDefinition is intentionally strict.  Validating its JSON
        # representation (rather than a Python dict) preserves JSON-native
        # conversions such as RFC 3339 dates, enum strings and arrays/tuples.
        return ScenarioDefinition.model_validate_json(json.dumps(payload, ensure_ascii=False))
    except Exception as error:  # The domain model supplies the precise cause.
        raise ScenarioConfigurationError(f"Invalid scenario configuration in '{source.name}': {error}") from error


def _value(source: Any, *path: str, default: Any = None) -> Any:
    """Get a nested value from a dict or Pydantic-style domain object."""

    current = source
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return default
    return current


def _require(source: Any, source_file: Path, *path: str) -> Any:
    value = _value(source, *path)
    if value is None or (isinstance(value, str) and not value.strip()):
        dotted_path = ".".join(path)
        raise ScenarioConfigurationError(f"Invalid scenario configuration in '{source_file.name}': missing '{dotted_path}'")
    return value


def _string_list(value: Any, source_file: Path, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise ScenarioConfigurationError(f"Invalid scenario configuration in '{source_file.name}': '{field}' must be a non-empty list of strings")
    return tuple(value)


def _public_projection(definition: Any, source: Path) -> Scenario:
    """Map only approved public fields to the API response model.

    This adapter is intentionally explicit: hidden interests, BATNAs, limits,
    and other private scenario state can never reach a public endpoint merely
    because a new field was added to the JSON schema.
    """

    # The complete domain model keeps briefing data together.  Accept the
    # temporary flat spelling only while migrating older JSON fixtures.
    estimated_minutes = _value(definition, "public_briefing", "estimated_minutes")
    if estimated_minutes is None:
        estimated_minutes = _require(definition, source, "estimated_minutes")
    if not isinstance(estimated_minutes, int) or isinstance(estimated_minutes, bool) or estimated_minutes < 1:
        raise ScenarioConfigurationError(f"Invalid scenario configuration in '{source.name}': 'estimated_minutes' must be a positive integer")

    participant_role_id = _value(definition, "public_briefing", "participant_role_id")
    roles = _value(definition, "roles", default=())
    participant_role = next((role for role in roles if _value(role, "id") == participant_role_id), None)
    opponent_role = next((role for role in roles if _value(role, "id") != participant_role_id), None)
    if participant_role is None or opponent_role is None:
        # Compatibility path for a pre-domain schema; remove once all source
        # files use ScenarioDefinition.
        participant_name = _value(definition, "participant_role", "name")
        opponent_name = _value(definition, "opponent_role", "name")
    else:
        participant_name = _value(participant_role, "title")
        opponent_name = _value(opponent_role, "title")

    context = _value(definition, "public_briefing", "situation")
    if context is None:
        context = _require(definition, source, "public_briefing", "context")
    objective = _value(definition, "public_briefing", "objective")
    if objective is None:
        objective = _require(definition, source, "objective")
    methods = _value(definition, "methodology_modules")
    if methods is None:
        methods = _value(definition, "methods", default=[])

    scenario_id = str(_require(definition, source, "metadata", "id"))
    metadata = random_variant_metadata(scenario_id) or {
        "industry": "Промышленность" if scenario_id == "equipment-supply" else "Технологии",
        "theme": "Закупки" if scenario_id == "equipment-supply" else "Внутренние ресурсы",
        "negotiation_type": str(getattr(_value(definition, "negotiation_type", default="procurement"), "value", _value(definition, "negotiation_type", default="procurement"))),
        "role_tags": tuple(filter(None, (participant_name, opponent_name))),
    }

    return Scenario(
        id=scenario_id,
        version=str(_require(definition, source, "metadata", "version")),
        language=str(_require(definition, source, "metadata", "language")),
        title=str(_require(definition, source, "public_briefing", "title")),
        summary=str(_require(definition, source, "public_briefing", "summary")),
        context=str(context),
        participant_role=str(_require({"value": participant_name}, source, "value")),
        opponent_role=str(_require({"value": opponent_name}, source, "value")),
        objective=str(objective),
        estimated_minutes=estimated_minutes,
        configurable=True,
        tone=str(_value(definition, "tone", default="professional")),
        difficulty=str(_value(definition, "difficulty", default="medium")),
        max_turns=int(_value(definition, "turn_limits", "maximum", default=12)),
        methods=tuple(str(getattr(item, "value", item)) for item in _string_list(methods, source, "methodology_modules")),
        tasks=participant_tasks(definition),
        industry=str(metadata["industry"]),
        negotiation_type=str(metadata["negotiation_type"]),
        theme=str(metadata["theme"]),
        role_tags=tuple(str(item) for item in metadata["role_tags"]),
    )


def load_scenario_catalog(scenarios_path: Path = DEFAULT_SCENARIOS_PATH) -> ScenarioCatalog:
    """Load all and only published JSON scenarios, failing fast on mistakes."""

    if not scenarios_path.exists() or not scenarios_path.is_dir():
        raise ScenarioConfigurationError(f"Scenario directory does not exist: '{scenarios_path}'")

    files = tuple(sorted(scenarios_path.glob("*.json")))
    if not files:
        raise ScenarioConfigurationError(f"No scenario JSON files found in '{scenarios_path}'")

    scenarios: list[Scenario] = []
    definitions: list[ScenarioDefinition] = []
    seen_ids: set[str] = set()
    for source in files:
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ScenarioConfigurationError(f"Invalid JSON in '{source.name}': {error.msg}") from error
        except OSError as error:
            raise ScenarioConfigurationError(f"Cannot read scenario configuration '{source.name}': {error}") from error

        if not isinstance(payload, dict):
            raise ScenarioConfigurationError(f"Invalid scenario configuration in '{source.name}': root must be an object")
        definition = _read_scenario_definition(payload, source)
        status = _value(definition, "metadata", "status")
        status = getattr(status, "value", status)
        if status != "published":
            continue
        scenario = _public_projection(definition, source)
        if scenario.id in seen_ids:
            raise ScenarioConfigurationError(f"Duplicate published scenario id '{scenario.id}'")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)
        definitions.append(definition)

    for definition in build_random_scenarios(tuple(definitions)):
        source = Path(f"{definition.metadata.id}.generated.json")
        scenario = _public_projection(definition, source)
        if scenario.id in seen_ids:
            raise ScenarioConfigurationError(f"Duplicate published scenario id '{scenario.id}'")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)
        definitions.append(definition)

    if not scenarios:
        raise ScenarioConfigurationError(f"No published scenarios found in '{scenarios_path}'")
    return ScenarioCatalog(tuple(scenarios), tuple(definitions))


@lru_cache(maxsize=1)
def get_scenario_catalog() -> ScenarioCatalog:
    """Return the process-wide immutable catalog loaded at application startup."""

    return load_scenario_catalog()


def clear_scenario_catalog_cache() -> None:
    """Test-only helper for isolated startup checks."""

    get_scenario_catalog.cache_clear()

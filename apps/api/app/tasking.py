"""Public participant goals and deterministic completion checks.

The participant sees only their own acceptable boundaries. Opponent limits,
BATNA values and hidden interests never cross this boundary.
"""

from __future__ import annotations

from .domain.scenario import PreferenceDirection, ScenarioDefinition
from .engine import NegotiationOutcome
from .models import NegotiationSession, ScenarioTask, TaskCheck


def _number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _plural(value: float, one: str, few: str, many: str) -> str:
    if not value.is_integer():
        return many
    number = abs(int(value))
    if 11 <= number % 100 <= 14:
        return many
    if number % 10 == 1:
        return one
    if 2 <= number % 10 <= 4:
        return few
    return many


def display_issue_value(value: float, unit: str) -> str:
    normalized = unit.casefold()
    if "руб" in normalized and value >= 1_000_000:
        return f"{_number(value / 1_000_000)} млн рублей"
    if normalized == "миллионов рублей":
        return f"{_number(value)} млн рублей"
    if normalized == "процентов":
        return f"{_number(value)}%"
    if normalized == "процентов в день":
        return f"{_number(value)}% в день"
    forms = {
        "дней": ("день", "дня", "дней"),
        "месяцев": ("месяц", "месяца", "месяцев"),
        "человек": ("человек", "человека", "человек"),
        "часов в неделю": ("час в неделю", "часа в неделю", "часов в неделю"),
    }
    if normalized in forms:
        return f"{_number(value)} {_plural(value, *forms[normalized])}"
    return f"{_number(value)} {unit}"


def _display_boundary_value(value: float, unit: str) -> str:
    normalized = unit.casefold()
    if "руб" in normalized and value >= 1_000_000:
        return f"{_number(value / 1_000_000)} млн рублей"
    if normalized == "миллионов рублей":
        return f"{_number(value)} млн рублей"
    if normalized == "процентов":
        return f"{_number(value)}%"
    if normalized == "процентов в день":
        return f"{_number(value)}% в день"
    return f"{_number(value)} {unit}"


def participant_tasks(scenario: ScenarioDefinition) -> tuple[ScenarioTask, ...]:
    participant_id = scenario.public_briefing.participant_role_id
    tasks = [
        ScenarioTask(
            id="outcome.agreement",
            title=scenario.public_briefing.objective,
            description="Зафиксируйте полный и жизнеспособный итог переговоров.",
        )
    ]
    for issue in scenario.issues:
        boundary = issue.party_ranges[participant_id]
        comparison = (
            "не более"
            if boundary.direction is PreferenceDirection.MINIMIZE
            else "не менее"
        )
        target = _display_boundary_value(boundary.reservation, issue.unit)
        tasks.append(
            ScenarioTask(
                id=f"issue.{issue.id}",
                title=f"{issue.title}: {comparison} {target}",
                description=(
                    "Условие считается выполненным только после фиксации итогового "
                    "соглашения в допустимой для вашей роли границе."
                ),
            )
        )
    return tuple(tasks)


def evaluate_task_checks(
    scenario: ScenarioDefinition, session: NegotiationSession
) -> list[TaskCheck]:
    tasks = participant_tasks(scenario)
    agreement = (
        session.engine_state.outcome is NegotiationOutcome.AGREEMENT
        and session.engine_state.accepted_offer is not None
    )
    checks = [
        TaskCheck(
            id=tasks[0].id,
            title=tasks[0].title,
            status="met" if agreement else "not_met",
            explanation=(
                "Движок подтвердил полное соглашение сторон."
                if agreement
                else "Полное соглашение не было зафиксировано."
            ),
        )
    ]

    accepted = {
        item.issue_id: item.value
        for item in (session.engine_state.accepted_offer.values if agreement else ())
    }
    participant_id = scenario.public_briefing.participant_role_id
    task_by_id = {task.id: task for task in tasks}
    for issue in scenario.issues:
        task = task_by_id[f"issue.{issue.id}"]
        value = accepted.get(issue.id)
        boundary = issue.party_ranges[participant_id]
        within_boundary = False
        if value is not None:
            if boundary.direction is PreferenceDirection.MINIMIZE:
                within_boundary = value <= boundary.reservation + 1e-9
            else:
                within_boundary = value >= boundary.reservation - 1e-9

        accepted_value = display_issue_value(value, issue.unit) if value is not None else None
        checks.append(
            TaskCheck(
                id=task.id,
                title=task.title,
                status="met" if agreement and within_boundary else "not_met",
                explanation=(
                    f"В итоговом соглашении зафиксировано: {accepted_value}."
                    if agreement and within_boundary
                    else (
                        f"Итоговое значение {accepted_value} не соответствует заданной границе."
                        if value is not None
                        else "В подтверждённом соглашении это условие не зафиксировано."
                    )
                ),
                accepted_value=accepted_value,
            )
        )
    return checks


__all__ = ["display_issue_value", "evaluate_task_checks", "participant_tasks"]

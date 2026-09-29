from __future__ import annotations

from math import ceil, floor

from ..domain.scenario import PreferenceDirection, ScenarioDefinition, ZopaOverlap
from .contracts import (
    IssueValue,
    NegotiationOffer,
    OfferAssessment,
    ReservationViolation,
    RoleUtility,
)


def make_offer(
    proposer_role_id: str, values: tuple[IssueValue, ...], source_turn: int
) -> NegotiationOffer:
    canonical = tuple(sorted(values, key=lambda item: item.issue_id))
    return NegotiationOffer(
        proposer_role_id=proposer_role_id,
        values=canonical,
        source_turn=source_turn,
    )


def merge_offer(
    previous: NegotiationOffer | None,
    proposer_role_id: str,
    values: tuple[IssueValue, ...],
    source_turn: int,
) -> NegotiationOffer:
    merged = {item.issue_id: item.value for item in previous.values} if previous else {}
    merged.update({item.issue_id: item.value for item in values})
    return make_offer(
        proposer_role_id,
        tuple(IssueValue(issue_id=key, value=value) for key, value in merged.items()),
        source_turn,
    )


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _issue_utility(
    value: float,
    minimum: float,
    maximum: float,
    reservation: float,
    aspiration: float,
    direction: PreferenceDirection,
    batna_utility: int,
) -> float:
    """Map reservation to BATNA utility and aspiration to 100."""

    if direction is PreferenceDirection.MAXIMIZE:
        if value >= reservation:
            span = aspiration - reservation
            return 100.0 if span <= 0 else batna_utility + (
                (value - reservation) / span * (100 - batna_utility)
            )
        span = reservation - minimum
        return 0.0 if span <= 0 else (value - minimum) / span * batna_utility
    if value <= reservation:
        span = reservation - aspiration
        return 100.0 if span <= 0 else batna_utility + (
            (reservation - value) / span * (100 - batna_utility)
        )
    span = maximum - reservation
    return 0.0 if span <= 0 else (maximum - value) / span * batna_utility


def assess_offer(scenario: ScenarioDefinition, offer: NegotiationOffer) -> OfferAssessment:
    values = {item.issue_id: item.value for item in offer.values}
    issue_ids = {item.id for item in scenario.issues}
    complete = set(values) == issue_ids

    violations: list[ReservationViolation] = []
    utilities: list[RoleUtility] = []
    for role in scenario.roles:
        weighted_utility = 0.0
        included_weight = 0.0
        for issue in scenario.issues:
            value = values.get(issue.id)
            if value is None:
                continue
            party_range = issue.party_ranges[role.id]
            reservation_violated = (
                value < party_range.minimum
                or value > party_range.maximum
                or (
                    party_range.direction is PreferenceDirection.MAXIMIZE
                    and value < party_range.reservation
                )
                or (
                    party_range.direction is PreferenceDirection.MINIMIZE
                    and value > party_range.reservation
                )
            )
            if reservation_violated:
                violations.append(
                    ReservationViolation(role_id=role.id, issue_id=issue.id, value=value)
                )

            issue_utility = _issue_utility(
                value,
                party_range.minimum,
                party_range.maximum,
                party_range.reservation,
                party_range.aspiration,
                party_range.direction,
                role.batna.utility,
            )
            weight = issue.party_weights[role.id]
            weighted_utility += _bounded(issue_utility) * weight
            included_weight += weight

        utility = _bounded(weighted_utility / included_weight) if included_weight else 0.0
        utility = round(utility, 4)
        utilities.append(
            RoleUtility(
                role_id=role.id,
                utility=utility,
                batna_utility=role.batna.utility,
                meets_batna=complete and utility >= role.batna.utility,
            )
        )

    zopa_violations: list[str] = []
    zopa_by_issue = {item.issue_id: item for item in scenario.zopa}
    for issue_id, value in values.items():
        zopa = zopa_by_issue[issue_id]
        if not isinstance(zopa, ZopaOverlap) or not zopa.lower <= value <= zopa.upper:
            zopa_violations.append(issue_id)

    acceptable = (
        complete
        and not violations
        and not zopa_violations
        and all(item.meets_batna for item in utilities)
    )
    return OfferAssessment(
        complete=complete,
        acceptable_for_all=acceptable,
        zopa_violation_issue_ids=tuple(sorted(zopa_violations)),
        reservation_violations=tuple(
            sorted(violations, key=lambda item: (item.role_id, item.issue_id))
        ),
        role_utilities=tuple(utilities),
    )


def deterministic_counter_offer(
    scenario: ScenarioDefinition,
    opponent_role_id: str,
    source_turn: int,
    *,
    negotiation_progress: int = 0,
    participant_values: tuple[IssueValue, ...] = (),
) -> NegotiationOffer:
    """Anchor on two real disagreements, then earn a path into the ZOPA.

    The former all-issue ZOPA midpoint made the first counter acceptable to
    the participant in every published scenario.  Keep the opponent's two
    highest-priority conflicting issues at their aspiration initially.  Other
    issues can already be workable, leaving room for a focused package trade.
    Progress comes from substantive participant actions, not elapsed turns, so
    repeating a rejection does not make the opponent concede automatically.
    """

    participant_role_id = scenario.public_briefing.participant_role_id
    zopa_by_issue = {item.issue_id: item for item in scenario.zopa}
    disputed: list[tuple[float, str]] = []
    for issue in scenario.issues:
        aspiration = issue.party_ranges[opponent_role_id].aspiration
        participant = issue.party_ranges[participant_role_id]
        conflicts = (
            aspiration < participant.reservation
            if participant.direction is PreferenceDirection.MAXIMIZE
            else aspiration > participant.reservation
        )
        if conflicts and isinstance(zopa_by_issue[issue.id], ZopaOverlap):
            disputed.append((issue.party_weights[opponent_role_id], issue.id))
    disputed_ids = {
        issue_id
        for _weight, issue_id in sorted(disputed, key=lambda item: (-item[0], item[1]))[:2]
    }

    # One numeric demand alone does not earn a concession.  Questions,
    # listening, objective criteria and improved packages all increase the
    # engine's progress score; an unproductive refusal does not.
    concession = max(0.0, min(1.0, (negotiation_progress - 12) / 24.0))
    participant_by_issue = {item.issue_id: item.value for item in participant_values}
    values: list[IssueValue] = []
    for issue in scenario.issues:
        zopa = zopa_by_issue[issue.id]
        opponent_range = issue.party_ranges[opponent_role_id]
        aspiration = opponent_range.aspiration
        unit = issue.unit.casefold()
        if isinstance(zopa, ZopaOverlap):
            workable = (zopa.lower + zopa.upper) / 2.0
            if "человек" in unit:
                whole_people = (
                    floor(workable)
                    if opponent_range.direction is PreferenceDirection.MINIMIZE
                    else ceil(workable)
                )
                if zopa.lower <= whole_people <= zopa.upper:
                    workable = float(whole_people)
            value = (
                aspiration + (workable - aspiration) * concession
                if issue.id in disputed_ids
                else workable
            )
        else:
            value = aspiration
        if issue.id in disputed_ids and concession < 1.0:
            if "человек" in unit:
                value = round(value)
            elif "дн" in unit or "месяц" in unit:
                value = round(value)
            elif "руб" in unit and abs(value) >= 1_000_000:
                value = round(value / 100_000) * 100_000
            elif "миллион" in unit:
                value = round(value, 1)
        participant_value = participant_by_issue.get(issue.id)
        if participant_value is not None and opponent_range.minimum <= participant_value <= opponent_range.maximum:
            # Do not ask for less (or offer more) than the participant has
            # already put on the table on this issue.  A counter may improve
            # our position, but never gifts the other side an extra concession.
            value = (
                max(value, participant_value)
                if opponent_range.direction is PreferenceDirection.MAXIMIZE
                else min(value, participant_value)
            )
        values.append(IssueValue(issue_id=issue.id, value=round(value, 6)))
    return make_offer(opponent_role_id, tuple(values), source_turn)

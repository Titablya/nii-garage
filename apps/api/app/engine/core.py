from __future__ import annotations

from collections.abc import Mapping

from ..domain.scenario import (
    ConditionDefinition,
    ConditionOperator,
    DisclosureTrigger,
    ScenarioDefinition,
)
from .classifier import classify_action
from .contracts import (
    ActionTag,
    ClassifiedAction,
    DirectiveKind,
    EngineEvent,
    NegotiationOutcome,
    NegotiationState,
    NegotiationStatus,
    OpponentDirective,
    PreliminaryCommitment,
    ReasonCode,
    RoleBudget,
    Transition,
)
from .offers import assess_offer, deterministic_counter_offer, merge_offer


_ACTION_REASONS: dict[ActionTag, ReasonCode] = {
    ActionTag.OPEN_QUESTION: ReasonCode.OPEN_QUESTION_DETECTED,
    ActionTag.ACTIVE_LISTENING: ReasonCode.ACTIVE_LISTENING_DETECTED,
    ActionTag.OBJECTIVE_CRITERION: ReasonCode.OBJECTIVE_CRITERION_DETECTED,
    ActionTag.OPTION: ReasonCode.OPTION_DETECTED,
    ActionTag.MESO: ReasonCode.MESO_DETECTED,
    ActionTag.ANCHOR: ReasonCode.ANCHOR_DETECTED,
    ActionTag.CONDITIONAL_AGREEMENT: ReasonCode.CONDITIONAL_AGREEMENT_DETECTED,
    ActionTag.COMMITMENT: ReasonCode.COMMITMENT_DETECTED,
    ActionTag.PERSONAL_ATTACK: ReasonCode.PERSONAL_ATTACK_DETECTED,
    ActionTag.THREAT: ReasonCode.THREAT_DETECTED,
    ActionTag.UNILATERAL_CONCESSION: ReasonCode.UNILATERAL_CONCESSION_DETECTED,
    ActionTag.ACCEPT: ReasonCode.ACCEPT_DETECTED,
    ActionTag.REJECT: ReasonCode.REJECT_DETECTED,
    ActionTag.WALK_AWAY: ReasonCode.WALK_AWAY_DETECTED,
}


def _bounded(value: int) -> int:
    return max(0, min(100, value))


def _role_ids(scenario: ScenarioDefinition) -> tuple[str, str]:
    participant = scenario.public_briefing.participant_role_id
    opponent = next(role.id for role in scenario.roles if role.id != participant)
    return participant, opponent


def initial_state(scenario: ScenarioDefinition) -> NegotiationState:
    participant, opponent = _role_ids(scenario)
    budgets = tuple(
        sorted(
            (
                RoleBudget(role_id=role_id, remaining=float(amount))
                for role_id, amount in scenario.initial_state.concession_budget.items()
            ),
            key=lambda item: item.role_id,
        )
    )
    return NegotiationState(
        scenario_version_id=scenario.metadata.version_id,
        participant_role_id=participant,
        opponent_role_id=opponent,
        trust=scenario.initial_state.trust,
        tension=scenario.initial_state.tension,
        progress=scenario.initial_state.progress,
        relationship=scenario.initial_state.relationship,
        turn_count=0,
        concession_budget=budgets,
    )


def _validate_state_for_scenario(
    scenario: ScenarioDefinition, state: NegotiationState
) -> None:
    participant, opponent = _role_ids(scenario)
    if state.scenario_version_id != scenario.metadata.version_id:
        raise ValueError("State belongs to another scenario version")
    if (state.participant_role_id, state.opponent_role_id) != (participant, opponent):
        raise ValueError("State roles do not match the scenario")
    expected_roles = sorted(role.id for role in scenario.roles)
    if [item.role_id for item in state.concession_budget] != expected_roles:
        raise ValueError("State concession budget roles do not match the scenario")


def _terminal_directive(state: NegotiationState) -> OpponentDirective:
    if state.outcome is NegotiationOutcome.AGREEMENT:
        return OpponentDirective(
            kind=DirectiveKind.ACCEPT,
            template_key="opponent.accept",
            offer=state.accepted_offer,
            reason_codes=(ReasonCode.TERMINAL_STATE_IGNORED,),
        )
    if state.outcome is NegotiationOutcome.WALK_AWAY:
        return OpponentDirective(
            kind=DirectiveKind.WALK_AWAY,
            template_key="opponent.walk_away",
            reason_codes=(ReasonCode.TERMINAL_STATE_IGNORED,),
        )
    return OpponentDirective(
        kind=DirectiveKind.IMPASSE,
        template_key="opponent.impasse",
        reason_codes=(ReasonCode.TERMINAL_STATE_IGNORED,),
    )


def _apply_signal_deltas(action: ClassifiedAction) -> tuple[int, int, int, int]:
    trust = tension = progress = relationship = 0
    effects: dict[ActionTag, tuple[int, int, int, int]] = {
        ActionTag.OPEN_QUESTION: (2, -1, 3, 1),
        ActionTag.ACTIVE_LISTENING: (5, -4, 4, 4),
        ActionTag.OBJECTIVE_CRITERION: (3, -1, 5, 1),
        ActionTag.OPTION: (0, 0, 5, 0),
        ActionTag.MESO: (2, -1, 7, 1),
        ActionTag.ANCHOR: (0, 2, 2, 0),
        ActionTag.CONDITIONAL_AGREEMENT: (2, -1, 5, 1),
        ActionTag.COMMITMENT: (3, -2, 8, 2),
        ActionTag.PERSONAL_ATTACK: (-12, 15, -5, -12),
        ActionTag.THREAT: (-15, 20, -5, -15),
        ActionTag.UNILATERAL_CONCESSION: (-2, 1, 2, -1),
        ActionTag.REJECT: (-1, 3, 0, -1),
    }
    for tag in action.tags:
        delta = effects.get(tag)
        if delta:
            trust += delta[0]
            tension += delta[1]
            progress += delta[2]
            relationship += delta[3]
    if action.issue_values:
        progress += 4
    return trust, tension, progress, relationship


def _disclosures(
    scenario: ScenarioDefinition,
    disclosed: set[str],
    open_question_count: int,
    active_listening_count: int,
    trust: int,
    turn_count: int,
    opponent_role_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]]:
    hidden_owner: dict[str, str] = {
        interest.id: role.id for role in scenario.roles for interest in role.hidden_interests
    }
    public_facts: list[str] = []
    triggered: list[tuple[str, str]] = []
    for rule in scenario.disclosure_rules:
        # The engine may only reveal information owned by the simulated
        # opponent. Participant-owned secrets never enter public output.
        if rule.owner_role_id != opponent_role_id:
            continue
        if rule.hidden_interest_id in disclosed:
            continue
        applies = False
        if rule.trigger is DisclosureTrigger.OPEN_QUESTION:
            applies = open_question_count >= rule.threshold
        elif rule.trigger is DisclosureTrigger.ACTIVE_LISTENING:
            applies = active_listening_count >= rule.threshold
        elif rule.trigger is DisclosureTrigger.TRUST:
            applies = trust >= rule.threshold
        elif rule.trigger is DisclosureTrigger.TURN:
            applies = turn_count >= rule.threshold
        elif rule.trigger is DisclosureTrigger.RECIPROCAL_DISCLOSURE:
            applies = any(
                hidden_owner.get(item) != rule.owner_role_id for item in disclosed
            ) and len(disclosed) >= rule.threshold
        if applies:
            disclosed.add(rule.hidden_interest_id)
            public_facts.append(rule.reveal_message)
            triggered.append((rule.owner_role_id, rule.hidden_interest_id))
    return tuple(sorted(disclosed)), tuple(public_facts), tuple(triggered)


def _predicate_value(
    condition_metric: str,
    role_id: str | None,
    issue_id: str | None,
    assessment,
    current_offer,
    action: ClassifiedAction,
    runtime_metrics: Mapping[str, object],
):
    if condition_metric in runtime_metrics:
        return runtime_metrics[condition_metric]
    if (
        condition_metric == "offer_utility"
        and role_id
        and assessment is not None
        and assessment.complete
    ):
        utility = next(
            (item.utility for item in assessment.role_utilities if item.role_id == role_id),
            None,
        )
        return utility
    if condition_metric == "compensation_present":
        return ActionTag.CONDITIONAL_AGREEMENT in action.tags
    if current_offer is not None:
        values = {item.issue_id: item.value for item in current_offer.values}
        if issue_id and condition_metric == issue_id:
            return values.get(issue_id)
        if condition_metric in values:
            return values[condition_metric]
    return None


def _compare(actual, operator: ConditionOperator, expected) -> bool:
    if actual is None:
        return False
    if operator is ConditionOperator.EQ:
        return actual == expected
    if operator is ConditionOperator.NE:
        return actual != expected
    if operator is ConditionOperator.GTE:
        return actual >= expected
    if operator is ConditionOperator.LTE:
        return actual <= expected
    if operator is ConditionOperator.GT:
        return actual > expected
    if operator is ConditionOperator.LT:
        return actual < expected
    if operator is ConditionOperator.IN:
        return actual in expected if isinstance(expected, (tuple, list, set, str)) else False
    return False


def _condition_matches(
    condition: ConditionDefinition,
    assessment,
    current_offer,
    action: ClassifiedAction,
    runtime_metrics: Mapping[str, object] | None = None,
) -> bool:
    metrics = runtime_metrics or {}
    matches = [
        _compare(
            _predicate_value(
                predicate.metric,
                predicate.role_id,
                predicate.issue_id,
                assessment,
                current_offer,
                action,
                metrics,
            ),
            predicate.operator,
            predicate.value,
        )
        for predicate in condition.predicates
    ]
    return all(matches) if condition.match == "all" else any(matches)


def _budget_after_action(
    state: NegotiationState, action: ClassifiedAction, counter_created: bool
) -> tuple[RoleBudget, ...]:
    amounts = {item.role_id: item.remaining for item in state.concession_budget}
    participant_cost = 0.0
    if ActionTag.UNILATERAL_CONCESSION in action.tags:
        participant_cost += 4.0
    if ActionTag.CONDITIONAL_AGREEMENT in action.tags:
        participant_cost += 1.0
    amounts[state.participant_role_id] = max(
        0.0, amounts[state.participant_role_id] - participant_cost
    )
    if counter_created:
        amounts[state.opponent_role_id] = max(0.0, amounts[state.opponent_role_id] - 1.0)
    return tuple(
        RoleBudget(role_id=role_id, remaining=round(amount, 4))
        for role_id, amount in sorted(amounts.items())
    )


def transition_turn(
    scenario: ScenarioDefinition, state: NegotiationState, text: str
) -> Transition:
    """Apply one participant turn as a pure deterministic state transition."""

    _validate_state_for_scenario(scenario, state)
    action = classify_action(scenario, state, text)
    if state.status is NegotiationStatus.COMPLETED:
        event = EngineEvent(sequence=1, code=ReasonCode.TERMINAL_STATE_IGNORED)
        return Transition(
            scenario_version_id=state.scenario_version_id,
            from_turn=state.turn_count,
            to_turn=state.turn_count,
            action=action,
            state=state,
            events=(event,),
            directive=_terminal_directive(state),
        )

    raw_events: list[tuple[ReasonCode, dict[str, object]]] = [
        (ReasonCode.TURN_PROCESSED, {})
    ]
    for tag in action.tags:
        raw_events.append((_ACTION_REASONS[tag], {"action_tag": tag}))

    next_turn = state.turn_count + 1
    open_count = state.open_question_count + int(ActionTag.OPEN_QUESTION in action.tags)
    listening_count = state.active_listening_count + int(
        ActionTag.ACTIVE_LISTENING in action.tags
    )
    trust_delta, tension_delta, progress_delta, relationship_delta = _apply_signal_deltas(
        action
    )
    trust = _bounded(state.trust + trust_delta)
    tension = _bounded(state.tension + tension_delta)
    progress = _bounded(state.progress + progress_delta)
    relationship = _bounded(state.relationship + relationship_delta)

    current_offer = state.current_offer
    assessment = assess_offer(scenario, current_offer) if current_offer else None
    offer_changed = False
    if action.issue_values:
        current_offer = merge_offer(
            state.current_offer,
            state.participant_role_id,
            action.issue_values,
            next_turn,
        )
        assessment = assess_offer(scenario, current_offer)
        offer_changed = current_offer.values != (
            state.current_offer.values if state.current_offer else ()
        )
        raw_events.append((ReasonCode.OFFER_EXTRACTED, {}))
        if assessment.complete:
            if assessment.zopa_violation_issue_ids:
                for issue_id in assessment.zopa_violation_issue_ids:
                    raw_events.append(
                        (ReasonCode.OFFER_OUTSIDE_ZOPA, {"issue_id": issue_id})
                    )
            else:
                raw_events.append((ReasonCode.OFFER_IN_ZOPA, {}))
        else:
            raw_events.append((ReasonCode.OFFER_INCOMPLETE, {}))
        for violation in assessment.reservation_violations:
            raw_events.append(
                (
                    ReasonCode.OFFER_RESERVATION_VIOLATION,
                    {
                        "issue_id": violation.issue_id,
                        "value": violation.value,
                    },
                )
            )
        if assessment.complete and any(
            not utility.meets_batna for utility in assessment.role_utilities
        ):
            raw_events.append((ReasonCode.OFFER_BELOW_BATNA, {}))

    meaningful = bool(
        set(action.tags)
        & {
            ActionTag.OPEN_QUESTION,
            ActionTag.ACTIVE_LISTENING,
            ActionTag.OBJECTIVE_CRITERION,
            ActionTag.OPTION,
            ActionTag.CONDITIONAL_AGREEMENT,
            ActionTag.COMMITMENT,
        }
    )
    if offer_changed or (meaningful and action.signature != state.last_action_signature):
        stagnant_turns = 0
    else:
        stagnant_turns = state.stagnant_turns + 1

    disclosed, disclosed_facts, triggered = _disclosures(
        scenario,
        set(state.disclosed_interest_ids),
        open_count,
        listening_count,
        trust,
        next_turn,
        state.opponent_role_id,
    )
    if triggered:
        trust = _bounded(trust + 2 * len(triggered))
        progress = _bounded(progress + 4 * len(triggered))
        stagnant_turns = 0
        for _role_id, _interest_id in triggered:
            raw_events.append((ReasonCode.INTEREST_DISCLOSED, {}))

    commitments = list(state.preliminary_commitments)
    if ActionTag.COMMITMENT in action.tags:
        commitments.append(
            PreliminaryCommitment(
                turn=next_turn,
                role_id=state.participant_role_id,
                text=action.normalized_text,
            )
        )

    if next_turn >= scenario.turn_limits.warning_at:
        raw_events.append((ReasonCode.TURN_WARNING, {}))
    if next_turn >= scenario.turn_limits.maximum:
        raw_events.append((ReasonCode.TURN_LIMIT_REACHED, {}))

    commitment_required = any(
        predicate.metric == "commitments_complete"
        and predicate.operator is ConditionOperator.EQ
        and predicate.value is True
        for condition in scenario.success_conditions
        for predicate in condition.predicates
    )
    commitments_complete = bool(commitments) or ActionTag.COMMITMENT in action.tags
    # A single amended issue inherits the opponent's other terms for context,
    # but it is not the participant's full package.  Do not interpret that
    # inherited mix as the participant walking away from their own BATNA.
    submitted_full_package = {item.issue_id for item in action.issue_values} == {
        issue.id for issue in scenario.issues
    }
    walk_condition_matched = current_offer is not None and (
        submitted_full_package or (ActionTag.ACCEPT in action.tags and not action.issue_values)
    ) and any(
        _condition_matches(condition, assessment, current_offer, action)
        for condition in scenario.walk_away_conditions
    )
    impasse_condition_matched = next_turn >= scenario.turn_limits.minimum and any(
        _condition_matches(
            condition,
            assessment,
            current_offer,
            action,
            {
                "stagnant_turns": stagnant_turns,
                "new_information": bool(triggered),
                "interests_discovered": len(disclosed),
            },
        )
        for condition in scenario.impasse_conditions
    )

    status = NegotiationStatus.ACTIVE
    outcome: NegotiationOutcome | None = None
    accepted_offer = None
    directive_kind: DirectiveKind
    template_key: str
    directive_offer = None
    directive_reasons: tuple[ReasonCode, ...]
    counter_created = False

    if ActionTag.WALK_AWAY in action.tags:
        status = NegotiationStatus.COMPLETED
        outcome = NegotiationOutcome.WALK_AWAY
        directive_kind = DirectiveKind.WALK_AWAY
        template_key = "opponent.walk_away"
        directive_reasons = (ReasonCode.WALK_AWAY_REACHED,)
        raw_events.append((ReasonCode.WALK_AWAY_REACHED, {}))
    elif assessment is not None and assessment.acceptable_for_all and (
        action.issue_values
        or ActionTag.ACCEPT in action.tags
        or ActionTag.COMMITMENT in action.tags
    ) and (
        not commitment_required or commitments_complete
    ):
        status = NegotiationStatus.COMPLETED
        outcome = NegotiationOutcome.AGREEMENT
        accepted_offer = current_offer
        directive_kind = DirectiveKind.ACCEPT
        template_key = "opponent.accept"
        directive_offer = current_offer
        directive_reasons = (ReasonCode.OFFER_IN_ZOPA, ReasonCode.AGREEMENT_REACHED)
        progress = 100
        raw_events.append((ReasonCode.AGREEMENT_REACHED, {}))
    elif walk_condition_matched:
        status = NegotiationStatus.COMPLETED
        outcome = NegotiationOutcome.WALK_AWAY
        directive_kind = DirectiveKind.WALK_AWAY
        template_key = "opponent.walk_away"
        directive_reasons = (
            ReasonCode.WALK_AWAY_CONDITION_MATCHED,
            ReasonCode.WALK_AWAY_REACHED,
        )
        raw_events.append((ReasonCode.WALK_AWAY_CONDITION_MATCHED, {}))
        raw_events.append((ReasonCode.WALK_AWAY_REACHED, {}))
    elif (
        assessment is not None
        and assessment.acceptable_for_all
        and commitment_required
        and not commitments_complete
        and next_turn < scenario.turn_limits.maximum
    ):
        directive_kind = DirectiveKind.CLARIFY
        template_key = "opponent.clarify_commitment"
        directive_reasons = (ReasonCode.COMMITMENT_REQUIRED,)
        raw_events.append((ReasonCode.COMMITMENT_REQUIRED, {}))
    elif (
        next_turn >= scenario.turn_limits.minimum
        and (impasse_condition_matched or (trust <= 10 and tension >= 85))
    ):
        status = NegotiationStatus.COMPLETED
        outcome = NegotiationOutcome.IMPASSE
        directive_kind = DirectiveKind.IMPASSE
        template_key = "opponent.impasse"
        directive_reasons = (ReasonCode.IMPASSE_REACHED,)
        raw_events.append((ReasonCode.IMPASSE_REACHED, {}))
    elif next_turn >= scenario.turn_limits.maximum:
        opponent_utility = next(
            (
                item
                for item in (assessment.role_utilities if assessment else ())
                if item.role_id == state.opponent_role_id
            ),
            None,
        )
        status = NegotiationStatus.COMPLETED
        if opponent_utility is not None and not opponent_utility.meets_batna:
            outcome = NegotiationOutcome.WALK_AWAY
            directive_kind = DirectiveKind.WALK_AWAY
            template_key = "opponent.walk_away"
            directive_reasons = (
                ReasonCode.TURN_LIMIT_REACHED,
                ReasonCode.OFFER_BELOW_BATNA,
                ReasonCode.WALK_AWAY_REACHED,
            )
            raw_events.append((ReasonCode.WALK_AWAY_REACHED, {}))
        else:
            outcome = NegotiationOutcome.IMPASSE
            directive_kind = DirectiveKind.IMPASSE
            template_key = "opponent.impasse"
            directive_reasons = (
                ReasonCode.TURN_LIMIT_REACHED,
                ReasonCode.IMPASSE_REACHED,
            )
            raw_events.append((ReasonCode.IMPASSE_REACHED, {}))
    elif action.issue_values or ActionTag.REJECT in action.tags or ActionTag.ACCEPT in action.tags:
        directive_kind = DirectiveKind.COUNTER
        template_key = "opponent.counter"
        directive_offer = deterministic_counter_offer(
            scenario,
            state.opponent_role_id,
            next_turn,
            negotiation_progress=progress,
            participant_values=action.issue_values,
        )
        current_offer = directive_offer
        counter_created = True
        directive_reasons = (
            ReasonCode.OFFER_RESERVATION_VIOLATION
            if assessment and assessment.reservation_violations
            else ReasonCode.COUNTER_OFFER_CREATED,
        )
        raw_events.append((ReasonCode.COUNTER_OFFER_CREATED, {}))
    else:
        directive_kind = DirectiveKind.CLARIFY
        template_key = "opponent.clarify"
        directive_reasons = (ReasonCode.CLARIFICATION_REQUESTED,)
        raw_events.append((ReasonCode.CLARIFICATION_REQUESTED, {}))

    public_facts = list(disclosed_facts)
    if directive_kind is DirectiveKind.CLARIFY and not public_facts:
        public_facts.append(scenario.public_briefing.known_facts[0])
    directive = OpponentDirective(
        kind=directive_kind,
        template_key=template_key,
        offer=directive_offer,
        public_facts=tuple(public_facts),
        reason_codes=directive_reasons,
    )

    next_state = NegotiationState(
        scenario_version_id=state.scenario_version_id,
        participant_role_id=state.participant_role_id,
        opponent_role_id=state.opponent_role_id,
        trust=trust,
        tension=tension,
        progress=progress,
        relationship=relationship,
        turn_count=next_turn,
        disclosed_interest_ids=disclosed,
        concession_budget=_budget_after_action(state, action, counter_created),
        current_offer=current_offer,
        accepted_offer=accepted_offer,
        preliminary_commitments=tuple(commitments),
        status=status,
        outcome=outcome,
        open_question_count=open_count,
        active_listening_count=listening_count,
        stagnant_turns=stagnant_turns,
        last_action_signature=action.signature,
    )
    events = tuple(
        EngineEvent(sequence=index, code=code, **details)
        for index, (code, details) in enumerate(raw_events, start=1)
    )
    return Transition(
        scenario_version_id=state.scenario_version_id,
        from_turn=state.turn_count,
        to_turn=next_turn,
        action=action,
        state=next_state,
        events=events,
        directive=directive,
    )

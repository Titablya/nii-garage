"""Pure deterministic negotiation engine.

Public entry points are ``initial_state``, ``classify_action``,
``extract_issue_values``, ``assess_offer`` and ``transition_turn``.  The
package intentionally has no web, persistence or LLM dependency.
"""

from .classifier import classify_action, extract_issue_values
from .contracts import (
    ActionTag,
    ClassifiedAction,
    DirectiveKind,
    EngineEvent,
    IssueValue,
    NegotiationOffer,
    NegotiationOutcome,
    NegotiationState,
    NegotiationStatus,
    OfferAssessment,
    OpponentDirective,
    ReasonCode,
    Transition,
)
from .core import initial_state, transition_turn
from .offers import assess_offer, deterministic_counter_offer, make_offer, merge_offer

__all__ = [
    "ActionTag",
    "ClassifiedAction",
    "DirectiveKind",
    "EngineEvent",
    "IssueValue",
    "NegotiationOffer",
    "NegotiationOutcome",
    "NegotiationState",
    "NegotiationStatus",
    "OfferAssessment",
    "OpponentDirective",
    "ReasonCode",
    "Transition",
    "assess_offer",
    "classify_action",
    "deterministic_counter_offer",
    "extract_issue_values",
    "initial_state",
    "make_offer",
    "merge_offer",
    "transition_turn",
]

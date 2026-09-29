from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .scenario import Identifier, MethodologyModule, NonEmptyText


ScenarioVersionId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9._-]*:v[1-9][0-9]*$", max_length=80),
]
RubricVersion = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+$", max_length=16)]
EvidenceQuote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class GoldenDialogueModel(BaseModel):
    """Strict and immutable base for hand-authored reference dialogues."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class GoldenCaseType(StrEnum):
    STRONG_SUCCESS = "strong_success"
    WEAK = "weak"
    AGREEMENT_BAD_PROCESS = "agreement_bad_process"
    STRONG_PROCESS_BAD_RESULT = "strong_process_bad_result"
    IMPASSE = "impasse"


class DialogueOutcome(StrEnum):
    AGREEMENT = "agreement"
    IMPASSE = "impasse"
    WALK_AWAY = "walk_away"


class ProcessQuality(StrEnum):
    STRONG = "strong"
    WEAK = "weak"
    MIXED = "mixed"


class DialogueRole(StrEnum):
    PARTICIPANT = "participant"
    OPPONENT = "opponent"


class RubricBlockId(StrEnum):
    PREPARATION = "preparation"
    PROCESS = "process"
    VALUE = "value"
    RESULT = "result"
    RELATIONSHIP = "relationship"


class RubricPenaltyId(StrEnum):
    PERSONAL_ATTACK = "penalty.personal_attack"
    THREAT = "penalty.threat"
    UNILATERAL_CONCESSION = "penalty.unilateral_concession"
    FABRICATED_FACT = "penalty.fabricated_fact"
    IGNORED_CONCERN = "penalty.ignored_concern"


class ObservableIndicator(StrEnum):
    I1 = "I1"
    I2 = "I2"
    I3 = "I3"
    I4 = "I4"
    I5 = "I5"
    I6 = "I6"
    I7 = "I7"
    I8 = "I8"
    I9 = "I9"
    I10 = "I10"
    I11 = "I11"
    I12 = "I12"
    I13 = "I13"
    N1 = "N1"
    N2 = "N2"
    N3 = "N3"
    N4 = "N4"
    N5 = "N5"


class EvidenceReference(GoldenDialogueModel):
    message_sequence: int = Field(ge=1)
    quote: EvidenceQuote


class ObservableAnnotation(GoldenDialogueModel):
    indicator_id: ObservableIndicator
    methodology_modules: tuple[MethodologyModule, ...] = Field(default_factory=tuple)
    rationale: NonEmptyText
    evidence: EvidenceReference

    @model_validator(mode="after")
    def validate_unique_modules(self) -> "ObservableAnnotation":
        if len(self.methodology_modules) != len(set(self.methodology_modules)):
            raise ValueError("methodology_modules аннотации должны быть уникальны")
        return self


class AlternativeParticipantUtterance(GoldenDialogueModel):
    text: NonEmptyText
    rationale: NonEmptyText
    expected_indicators: tuple[ObservableIndicator, ...] = Field(min_length=1)
    methodology_modules: tuple[MethodologyModule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_references(self) -> "AlternativeParticipantUtterance":
        if len(self.expected_indicators) != len(set(self.expected_indicators)):
            raise ValueError("expected_indicators альтернативы должны быть уникальны")
        if any(indicator.value.startswith("N") for indicator in self.expected_indicators):
            raise ValueError("Улучшенная альтернативная реплика может ожидать только I-индикаторы")
        if len(self.methodology_modules) != len(set(self.methodology_modules)):
            raise ValueError("methodology_modules альтернативы должны быть уникальны")
        return self


class GoldenDialogueMessage(GoldenDialogueModel):
    sequence: int = Field(ge=1)
    role: DialogueRole
    text: NonEmptyText
    annotations: tuple[ObservableAnnotation, ...] = Field(default_factory=tuple, max_length=2)
    alternative_participant_utterance: AlternativeParticipantUtterance | None = None

    @model_validator(mode="after")
    def validate_participant_only_material(self) -> "GoldenDialogueMessage":
        if self.role is not DialogueRole.PARTICIPANT:
            if self.annotations:
                raise ValueError("Наблюдаемые индикаторы могут аннотировать только реплики участника")
            if self.alternative_participant_utterance is not None:
                raise ValueError("Альтернативная реплика допустима только для реплики участника")

        indicator_ids = [item.indicator_id for item in self.annotations]
        if len(indicator_ids) != len(set(indicator_ids)):
            raise ValueError("Одна реплика не может содержать один индикатор дважды")
        for annotation in self.annotations:
            if annotation.evidence.message_sequence != self.sequence:
                raise ValueError("Ссылка evidence должна указывать на аннотируемую реплику")
            if annotation.evidence.quote.casefold() not in self.text.casefold():
                raise ValueError("Цитата evidence должна быть точным фрагментом реплики")
        return self


class ExpectedStateDelta(GoldenDialogueModel):
    trust: int = Field(ge=-100, le=100)
    tension: int = Field(ge=-100, le=100)
    progress: int = Field(ge=-100, le=100)
    relationship: int = Field(ge=-100, le=100)
    concession_budget_delta: dict[Identifier, float] = Field(min_length=2, max_length=2)


class ScoreBand(GoldenDialogueModel):
    minimum: int = Field(ge=0, le=100)
    maximum: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_order(self) -> "ScoreBand":
        if self.minimum > self.maximum:
            raise ValueError("minimum оценки не может быть больше maximum")
        return self


class BlockExpectation(GoldenDialogueModel):
    block_id: RubricBlockId
    minimum_points: int = Field(ge=0, le=100)
    maximum_points: int = Field(ge=0, le=100)
    rationale: NonEmptyText
    evidence_sequences: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range_and_evidence(self) -> "BlockExpectation":
        if self.minimum_points > self.maximum_points:
            raise ValueError("minimum_points блока не может быть больше maximum_points")
        rubric_maximum = {
            RubricBlockId.PREPARATION: 20,
            RubricBlockId.PROCESS: 25,
            RubricBlockId.VALUE: 20,
            RubricBlockId.RESULT: 25,
            RubricBlockId.RELATIONSHIP: 10,
        }[self.block_id]
        if self.maximum_points > rubric_maximum:
            raise ValueError(
                f"maximum_points блока {self.block_id.value} не может превышать {rubric_maximum}"
            )
        if len(self.evidence_sequences) != len(set(self.evidence_sequences)):
            raise ValueError("evidence_sequences блока должны быть уникальны")
        if any(sequence < 1 for sequence in self.evidence_sequences):
            raise ValueError("evidence_sequences должны быть положительными")
        return self


class PenaltyExpectation(GoldenDialogueModel):
    penalty_id: RubricPenaltyId
    minimum_occurrences: int = Field(ge=0, le=100)
    maximum_occurrences: int = Field(ge=0, le=100)
    rationale: NonEmptyText
    evidence_sequences: tuple[int, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_range_and_evidence(self) -> "PenaltyExpectation":
        if self.minimum_occurrences > self.maximum_occurrences:
            raise ValueError("minimum_occurrences не может быть больше maximum_occurrences")
        if len(self.evidence_sequences) != len(set(self.evidence_sequences)):
            raise ValueError("evidence_sequences штрафа должны быть уникальны")
        if any(sequence < 1 for sequence in self.evidence_sequences):
            raise ValueError("evidence_sequences должны быть положительными")
        if self.maximum_occurrences == 0 and self.evidence_sequences:
            raise ValueError("У неприменимого штрафа не может быть evidence")
        if self.minimum_occurrences > 0 and not self.evidence_sequences:
            raise ValueError("Ожидаемый штраф должен ссылаться на evidence")
        return self


class ExpectedEvaluation(GoldenDialogueModel):
    outcome: DialogueOutcome
    process_quality: ProcessQuality
    state_delta: ExpectedStateDelta
    score_band: ScoreBand
    block_expectations: tuple[BlockExpectation, ...] = Field(min_length=1)
    penalties: tuple[PenaltyExpectation, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ExpectedEvaluation":
        block_ids = [item.block_id for item in self.block_expectations]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("block_id ожиданий должны быть уникальны")
        if set(block_ids) != set(RubricBlockId):
            raise ValueError("Ожидания должны покрывать все пять блоков рубрики")
        penalty_ids = [item.penalty_id for item in self.penalties]
        if len(penalty_ids) != len(set(penalty_ids)):
            raise ValueError("penalty_id ожиданий должны быть уникальны")
        return self


class GoldenDialogueDefinition(GoldenDialogueModel):
    """One labelled reference negotiation used for evaluation and learning."""

    schema_version: Literal["1.0"]
    dialogue_id: Annotated[
        str,
        StringConstraints(
            pattern=(
                r"^[a-z][a-z0-9._-]*:v[1-9][0-9]*:"
                r"(?:strong_success|weak|agreement_bad_process|strong_process_bad_result|impasse)$"
            ),
            max_length=120,
        ),
    ]
    scenario_version_id: ScenarioVersionId
    rubric_version: RubricVersion
    case_type: GoldenCaseType
    title: NonEmptyText
    learning_objective: NonEmptyText
    messages: tuple[GoldenDialogueMessage, ...] = Field(min_length=8, max_length=14)
    expected: ExpectedEvaluation
    methodological_explanation: NonEmptyText

    @model_validator(mode="after")
    def validate_dialogue(self) -> "GoldenDialogueDefinition":
        expected_id = f"{self.scenario_version_id}:{self.case_type.value}"
        if self.dialogue_id != expected_id:
            raise ValueError(f"dialogue_id должен быть каноническим и равен {expected_id}")

        sequences = [message.sequence for message in self.messages]
        if sequences != list(range(1, len(self.messages) + 1)):
            raise ValueError("sequence сообщений должен начинаться с 1 и идти без пропусков")
        if self.messages[0].role is not DialogueRole.PARTICIPANT:
            raise ValueError("Первую реплику диалога должен произносить participant")
        for previous, current in zip(self.messages, self.messages[1:], strict=False):
            if previous.role is current.role:
                raise ValueError("Роли participant и opponent должны строго чередоваться")

        participant_sequences = {
            message.sequence for message in self.messages if message.role is DialogueRole.PARTICIPANT
        }
        if not any(message.annotations for message in self.messages):
            raise ValueError("Диалог должен содержать хотя бы одну наблюдаемую аннотацию")
        for block in self.expected.block_expectations:
            self._require_participant_evidence(block.evidence_sequences, participant_sequences, block.block_id)
        for penalty in self.expected.penalties:
            self._require_participant_evidence(
                penalty.evidence_sequences, participant_sequences, penalty.penalty_id
            )

        if self.case_type is GoldenCaseType.STRONG_SUCCESS:
            if self.expected.outcome is not DialogueOutcome.AGREEMENT:
                raise ValueError("strong_success должен завершаться agreement")
            if self.expected.process_quality is not ProcessQuality.STRONG:
                raise ValueError("strong_success должен иметь strong process_quality")
        elif self.case_type is GoldenCaseType.AGREEMENT_BAD_PROCESS:
            if self.expected.outcome is not DialogueOutcome.AGREEMENT:
                raise ValueError("agreement_bad_process должен завершаться agreement")
            if self.expected.process_quality is not ProcessQuality.WEAK:
                raise ValueError("agreement_bad_process должен иметь weak process_quality")
        elif self.case_type is GoldenCaseType.STRONG_PROCESS_BAD_RESULT:
            if self.expected.process_quality is not ProcessQuality.STRONG:
                raise ValueError("strong_process_bad_result должен иметь strong process_quality")
            if self.expected.outcome is DialogueOutcome.AGREEMENT:
                raise ValueError("strong_process_bad_result не может завершаться agreement")
        elif self.case_type is GoldenCaseType.IMPASSE:
            if self.expected.outcome is not DialogueOutcome.IMPASSE:
                raise ValueError("impasse должен завершаться impasse")
        elif self.case_type is GoldenCaseType.WEAK and self.expected.process_quality is not ProcessQuality.WEAK:
            raise ValueError("weak должен иметь weak process_quality")
        return self

    @staticmethod
    def _require_participant_evidence(
        evidence_sequences: tuple[int, ...], participant_sequences: set[int], expectation_id: str
    ) -> None:
        invalid = set(evidence_sequences) - participant_sequences
        if invalid:
            formatted = ", ".join(str(value) for value in sorted(invalid))
            raise ValueError(
                f"Evidence ожидания {expectation_id} должно ссылаться только на participant: {formatted}"
            )

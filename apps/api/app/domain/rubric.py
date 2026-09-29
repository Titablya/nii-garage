from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", min_length=2, max_length=64),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class DomainModel(BaseModel):
    """Strict and assignment-immutable base for persisted definitions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class RubricCriterion(DomainModel):
    id: Identifier
    title: NonEmptyText
    max_points: int = Field(gt=0, le=100)
    evidence_required: bool = True
    description: NonEmptyText


class RubricBlock(DomainModel):
    id: Identifier
    title: NonEmptyText
    max_points: int = Field(gt=0, le=100)
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_points(self) -> "RubricBlock":
        if len({criterion.id for criterion in self.criteria}) != len(self.criteria):
            raise ValueError(f"Критерии блока {self.id} должны иметь уникальные id")
        if sum(criterion.max_points for criterion in self.criteria) != self.max_points:
            raise ValueError(f"Сумма критериев блока {self.id} должна быть равна max_points")
        return self


class RubricPenalty(DomainModel):
    id: Identifier
    title: NonEmptyText
    points: int = Field(lt=0, ge=-100)
    evidence_required: bool = True


class RubricDefinition(DomainModel):
    """A versioned deterministic scoring contract."""

    version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+$")]
    title: NonEmptyText
    total_points: int = Field(default=100, gt=0, le=100)
    blocks: tuple[RubricBlock, ...] = Field(min_length=1)
    penalties: tuple[RubricPenalty, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_totals_and_ids(self) -> "RubricDefinition":
        if sum(block.max_points for block in self.blocks) != self.total_points:
            raise ValueError("Сумма блоков рубрики должна быть равна total_points")

        ids = [block.id for block in self.blocks]
        ids.extend(criterion.id for block in self.blocks for criterion in block.criteria)
        ids.extend(penalty.id for penalty in self.penalties)
        if len(ids) != len(set(ids)):
            raise ValueError("Все id блоков, критериев и штрафов рубрики должны быть уникальны")
        return self


DEFAULT_RUBRIC_V01 = RubricDefinition.model_validate(
    {
        "version": "0.1",
        "title": "Базовая рубрика переговоров MVP",
        "total_points": 100,
        "blocks": (
            {
                "id": "preparation",
                "title": "Подготовка и защита интересов",
                "max_points": 20,
                "criteria": (
                    {
                        "id": "preparation.outcome",
                        "title": "Результат не хуже BATNA",
                        "max_points": 10,
                        "description": "Соглашение не нарушает границу выхода либо участник обоснованно прекращает переговоры.",
                    },
                    {
                        "id": "preparation.interests",
                        "title": "Выявление и защита интересов",
                        "max_points": 10,
                        "description": "Сторона защищает свои приоритеты и исследует интересы оппонента.",
                    },
                ),
            },
            {
                "id": "process",
                "title": "Качество процесса",
                "max_points": 25,
                "criteria": (
                    {
                        "id": "process.questions",
                        "title": "Вопросы и активное слушание",
                        "max_points": 12,
                        "description": "Вопросы и перефразирование дают новую информацию и влияют на следующую реплику.",
                    },
                    {
                        "id": "process.criteria",
                        "title": "Объективные критерии",
                        "max_points": 13,
                        "description": "Проверяемые ориентиры применены к предложению и согласованы сторонами.",
                    },
                ),
            },
            {
                "id": "value",
                "title": "Создание и обмен ценностью",
                "max_points": 20,
                "criteria": (
                    {
                        "id": "value.options",
                        "title": "Варианты и взаимные обмены",
                        "max_points": 12,
                        "description": "Созданы варианты по нескольким вопросам, уступки связаны со встречными условиями.",
                    },
                    {
                        "id": "value.modules",
                        "title": "Контекстные методы",
                        "max_points": 8,
                        "description": "Разрешённый сценарием метод применён уместно и дал наблюдаемый результат.",
                    },
                ),
            },
            {
                "id": "result",
                "title": "Качество результата",
                "max_points": 25,
                "criteria": (
                    {
                        "id": "result.quality",
                        "title": "Качество соглашения или выхода",
                        "max_points": 15,
                        "description": "Итог лучше альтернативы и соответствует допустимым границам либо выход дисциплинирован.",
                    },
                    {
                        "id": "result.commitments",
                        "title": "Реализуемость обязательств",
                        "max_points": 10,
                        "description": "Зафиксированы ответственные, действия, сроки, условия и метрики.",
                    },
                ),
            },
            {
                "id": "relationship",
                "title": "Отношения и деловой тон",
                "max_points": 10,
                "criteria": (
                    {
                        "id": "relationship.tone",
                        "title": "Уважительный деловой тон",
                        "max_points": 10,
                        "description": "Сторона сохраняет уважение и содержательно обрабатывает опасения.",
                    },
                ),
            },
        ),
        "penalties": (
            {"id": "penalty.personal_attack", "title": "Личная атака", "points": -8},
            {"id": "penalty.threat", "title": "Необоснованная угроза", "points": -10},
            {"id": "penalty.unilateral_concession", "title": "Односторонняя уступка", "points": -4},
            {"id": "penalty.fabricated_fact", "title": "Выдуманный факт", "points": -3},
            {"id": "penalty.ignored_concern", "title": "Игнорирование критичного опасения", "points": -3},
        ),
    }
)

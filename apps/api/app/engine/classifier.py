from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from ..domain.scenario import MethodologyModule, ScenarioDefinition
from .contracts import ActionTag, ClassifiedAction, IssueValue, NegotiationState
from .offers import assess_offer, make_offer


_NUMBER_TOKEN = r"\d{1,3}(?:[\s\u00a0]\d{3})+|\d+(?:[.,]\d+)?"
_NUMBER = re.compile(rf"(?<!\w)({_NUMBER_TOKEN})(?!\w)")
_UNIT_MODIFIERS = r"(?:(?:календарн|рабоч|выделенн|штатн|полноценн|полн)\w*\s+){0,2}"

_WORD_NUMBERS: tuple[tuple[str, str], ...] = (
    (r"полтор(?:а|ы)", "1.5"),
    (r"од(?:ин|на|но|ного|ной)", "1"),
    (r"дв(?:а|е|ух)", "2"),
    (r"тр(?:и|ех)", "3"),
    (r"четыр(?:е|ех)", "4"),
    (r"пят(?:ь|и)", "5"),
    (r"шест(?:ь|и)", "6"),
    (r"сем(?:ь|и)", "7"),
    (r"восем(?:ь|и)", "8"),
    (r"девят(?:ь|и)", "9"),
    (r"десят(?:ь|и)", "10"),
)

_ISSUE_PATTERNS: dict[str, tuple[str, str]] = {
    "price": (r"цен\w*|стоимост\w*|контракт\w*", r"млн\w*|миллион\w*|руб\w*"),
    "delivery_days": (r"поставк\w*|срок\w*|доставк\w*", r"дн\w*|день|дня|дней"),
    "prepayment": (r"предоплат\w*|аванс\w*", r"%|процент\w*"),
    "warranty_months": (r"гаранти\w*", r"месяц\w*|мес\.?"),
    "delay_penalty": (r"штраф\w*|неустойк\w*|просрочк\w*", r"%|процент\w*"),
    "budget": (r"бюджет\w*|финансирован\w*", r"млн\w*|миллион\w*|руб\w*"),
    "specialists": (r"специалист\w*|сотрудник\w*|человек\w*", r"специалист\w*|сотрудник\w*|человек\w*"),
    "start_days": (r"старт\w*|начал\w*|запуск\w*", r"дн\w*|день|дня|дней"),
    "reporting_hours": (r"отчет\w*|отчетност\w*|контрол\w*|встреч\w*", r"час\w*|ч(?:\.|\b)"),
}


def _normalize(text: str) -> str:
    normalized = text.casefold().replace("ё", "е").replace("\u00a0", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for pattern, value in _WORD_NUMBERS:
        normalized = re.sub(rf"\b(?:{pattern})\b", value, normalized)
    return normalized


def _parse_number(token: str) -> float:
    return float(token.replace("\u00a0", "").replace(" ", "").replace(",", "."))


def _is_range_endpoint(
    text: str, match: re.Match[str], unit_pattern: str
) -> bool:
    """Return whether a numeric token is part of a range rather than an offer.

    A reference such as ``9–11 млн`` is useful objective-criterion evidence, but
    neither boundary is an actionable price proposal.  Treating the upper bound
    as the current offer can incorrectly trigger reservation or walk-away rules.
    """

    before = text[max(0, match.start() - 48) : match.start()]
    after = text[match.end() : min(len(text), match.end() + 48)]
    # A dash between two numbers is a range; a dash after an issue label is
    # just punctuation in a perfectly valid offer ("Цена — 10,8 млн").
    if re.search(
        rf"(?:{_NUMBER_TOKEN})(?:\s*(?:{unit_pattern}))?\s*[-–—]\s*$",
        before,
        re.IGNORECASE,
    ) or re.match(r"\s*[-–—]", after):
        return True
    if re.search(r"\bот\b.{0,32}\bдо\s*$", before, re.IGNORECASE):
        return True
    if re.search(r"\bмежду\b.{0,32}\bи\s*$", before, re.IGNORECASE):
        return True
    if re.match(
        rf"\s*(?:{unit_pattern})(?!\w)\s*(?:[-–—]|\bдо\b)\s*(?:{_NUMBER_TOKEN})",
        after,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"\bмежду\b.{0,32}$", before, re.IGNORECASE) and re.match(
        rf"\s*(?:{unit_pattern})(?!\w)\s*\bи\b\s*(?:{_NUMBER_TOKEN})",
        after,
        re.IGNORECASE,
    ):
        return True
    return False


def _extract_issue_value(
    text: str, issue_id: str, maximum: float, *, prefer_last: bool = False
) -> float | None:
    patterns = _ISSUE_PATTERNS.get(issue_id)
    if patterns is None:
        return None
    alias_pattern, unit_pattern = patterns
    aliases = list(re.finditer(alias_pattern, text, re.IGNORECASE))
    ranked: list[tuple[int, int, re.Match[str]]] = []
    for match in _NUMBER.finditer(text):
        if _is_range_endpoint(text, match, unit_pattern):
            continue
        # A number belongs to an issue only when its unit follows directly.
        # This prevents `6 млн, 3 специалиста` from being read as six specialists.
        tail = text[match.end() : min(len(text), match.end() + 28)]
        if re.match(
            rf"\s*(?:[-–—,:]\s*)?{_UNIT_MODIFIERS}(?:{unit_pattern})(?!\w)",
            tail,
            re.IGNORECASE,
        ) is None:
            continue
        alias_distance = min(
            (
                min(abs(match.start() - alias.end()), abs(alias.start() - match.end()))
                for alias in aliases
            ),
            default=10_000,
        )
        # Percentages are ambiguous between prepayment and delay penalty and
        # therefore always require a nearby issue name.
        if issue_id in {"prepayment", "delay_penalty"} and alias_distance > 32:
            continue
        ranked.append((alias_distance, match.start(), match))

    # Prefer the number closest to the issue name; for unambiguous units a
    # standalone package such as `6 млн, 3 специалиста` is also valid.
    # When an issue name is present, proximity wins. If the speaker gives an
    # unlabelled range followed by a concrete package value (`9–11 млн, предлагаю
    # 9,5 млн`), the last value is the actionable one rather than the range edge.
    ranked.sort(key=lambda item: (item[0], -item[1] if prefer_last or item[0] == 10_000 else item[1]))
    candidates = [item[2] for item in ranked]

    # Compatibility for compact `бюджет 6` and explicit large ruble prices.
    if not candidates:
        for alias in aliases:
            after = _NUMBER.search(text, alias.end(), min(len(text), alias.end() + 24))
            if after is None:
                continue
            value = _parse_number(after.group(1))
            if issue_id == "budget" or (issue_id == "price" and value >= 1_000_000):
                candidates.append(after)
                break

    for match in candidates:
        value = _parse_number(match.group(1))
        if issue_id == "price" and maximum >= 1_000_000 and value < 1_000:
            value *= 1_000_000
        return round(value, 6)
    return None


def extract_issue_values(
    scenario: ScenarioDefinition, text: str, *, prefer_last: bool = False
) -> tuple[IssueValue, ...]:
    """Extract one deterministic numeric value per configured issue."""

    normalized = _normalize(text)
    values: list[IssueValue] = []
    for issue in scenario.issues:
        maximum = max(item.maximum for item in issue.party_ranges.values())
        value = _extract_issue_value(normalized, issue.id, maximum, prefer_last=prefer_last)
        if value is not None:
            values.append(IssueValue(issue_id=issue.id, value=value))
    return tuple(sorted(values, key=lambda item: item.issue_id))


def _contains(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def unquoted_text(text: str) -> str:
    """Do not attribute a cited opponent utterance to the current speaker."""

    return re.sub(r"«[^»]*»|“[^”]*”|\"[^\"]*\"", " ", text)


def _substantive_question(text: str) -> bool:
    return _contains(
        text,
        (
            r"важн|приоритет|интерес|потребност|ограничен|опасен|беспок|риск",
            r"проблем|последств|услови|срок|цен|стоимост|оплат|аванс|бюджет",
            r"поставк|доставк|гаранти|штраф|ресурс|команд|проект|программ",
            r"результат|цель|запуск|график|ответствен|предложен|пакет|решен",
        ),
    )


def _multiple_equivalent_offers(scenario: ScenarioDefinition, text: str) -> bool:
    """Require two distinct multi-issue packages with comparable proposer value."""

    if MethodologyModule.MESO not in scenario.methodology_modules:
        return False
    first = re.search(r"\bперв(?:ый|ое|ая)\s*[:—-]", text)
    second = re.search(r"\bвтор(?:ой|ое|ая)\s*[:—-]", text)
    if first is None or second is None or second.start() <= first.end():
        return False
    first_values = extract_issue_values(scenario, text[first.end():second.start()])
    second_values = extract_issue_values(scenario, text[second.end():])
    first_by_issue = {item.issue_id: item.value for item in first_values}
    second_by_issue = {item.issue_id: item.value for item in second_values}
    common = first_by_issue.keys() & second_by_issue.keys()
    if len(common) < 2 or not any(first_by_issue[key] != second_by_issue[key] for key in common):
        return False
    role_id = scenario.public_briefing.participant_role_id
    first_assessment = assess_offer(scenario, make_offer(role_id, first_values, source_turn=1))
    second_assessment = assess_offer(scenario, make_offer(role_id, second_values, source_turn=1))
    first_utility = next(item.utility for item in first_assessment.role_utilities if item.role_id == role_id)
    second_utility = next(item.utility for item in second_assessment.role_utilities if item.role_id == role_id)
    return abs(first_utility - second_utility) <= 10


def _criterion_ids(scenario: ScenarioDefinition, text: str) -> tuple[str, ...]:
    generic = _contains(
        text,
        (
            r"рын\w*",
            r"регламент\w*",
            r"стандарт\w*",
            r"статистик\w*",
            r"план\w* ресурс\w*",
            r"экономик\w* пилот\w*",
            r"коммерческ\w* предложен\w*",
            r"по данным",
        ),
    )
    matches: list[str] = []
    for criterion in scenario.objective_criteria:
        phrases = (_normalize(criterion.title), _normalize(criterion.source))
        if any(phrase in text for phrase in phrases) or (
            generic
            and any(
                word in text
                for phrase in phrases
                for word in re.findall(r"[а-яa-z]{6,}", phrase)
            )
        ):
            matches.append(criterion.id)
    if generic and not matches:
        matches.extend(item.id for item in scenario.objective_criteria)
    return tuple(sorted(set(matches)))


def classify_action(
    scenario: ScenarioDefinition, state: NegotiationState, text: str
) -> ClassifiedAction:
    normalized = _normalize(text)
    if not normalized:
        raise ValueError("Negotiation utterance must not be empty")

    # A cited counterpart utterance is context, not this speaker's action.
    behavioral_text = unquoted_text(normalized)
    issue_values = extract_issue_values(scenario, behavioral_text)
    criterion_ids = _criterion_ids(scenario, behavioral_text)
    tags: set[ActionTag] = set()

    if "?" in behavioral_text and _substantive_question(behavioral_text) and _contains(
        behavioral_text,
        (
            r"\bчто\b",
            r"\bкак\b",
            r"\bкакие?\b",
            r"\bпочему\b",
            r"\bкогда\b",
            r"\bнасколько\b",
            r"\bчто для вас\b",
        ),
    ):
        tags.add(ActionTag.OPEN_QUESTION)
    if _contains(
        behavioral_text,
        (
            r"правильно ли я понимаю",
            r"верно ли я понимаю",
            r"правильно понимаю",
            r"я слышу,? что",
            r"понимаю,? что",
            r"для вас (?:важно|критично)",
            r"вас (?:беспокоит|волнует)",
        ),
    ):
        tags.add(ActionTag.ACTIVE_LISTENING)
    if criterion_ids:
        tags.add(ActionTag.OBJECTIVE_CRITERION)
    if issue_values or _contains(behavioral_text, (r"\bпредлагаю\b", r"\bвариант\w*\b", r"\bпакет\w*\b")):
        tags.add(ActionTag.OPTION)
    if _multiple_equivalent_offers(scenario, behavioral_text):
        tags.add(ActionTag.MESO)
    if issue_values and (
        state.current_offer is None
        or _contains(behavioral_text, (r"отправн\w* точк\w*", r"начнем с", r"исходн\w* предложен\w*"))
    ):
        tags.add(ActionTag.ANCHOR)
    conditional_phrase = _contains(
        behavioral_text,
        (
            r"\bесли\b.+\bто\b",
            r"при условии",
            r"в обмен на",
            r"готов\w*.+если",
            r"соглас\w*.+если",
        ),
    )
    reciprocal_exchange = _contains(
        behavioral_text,
        (r"\bесли\s+вы\b.+\b(?:мы|я)\b", r"\bесли\s+(?:мы|я)\b.+\bвы\b", r"в обмен на"),
    )
    if conditional_phrase and (issue_values or reciprocal_exchange):
        tags.add(ActionTag.CONDITIONAL_AGREEMENT)
    if _contains(
        behavioral_text,
        (
            r"\bфиксируем\b",
            r"\bзафиксируем\b",
            r"\bобязуюсь\b",
            r"\bподтверждаю\b",
            r"\bответственн\w*",
            r"контрольн\w* точк\w*",
        ),
    ):
        tags.add(ActionTag.COMMITMENT)
    if _contains(
        behavioral_text,
        (
            r"не понимаете",
            r"некомпетент\w*",
            r"безответствен\w*",
            r"ваша вина",
            r"вы всегда.+тормоз",
            r"не умеете",
        ),
    ):
        tags.add(ActionTag.PERSONAL_ATTACK)
    if _contains(
        behavioral_text,
        (
            r"\bиначе\b.+(?:сообщу|пожалуюсь|увол\w*|накаж\w*|последств)",
            r"вынесу вопрос",
            r"сообщу руководств",
            r"пожалуюсь",
            r"увол\w*",
            r"накаж\w*",
            r"будут последствия",
        ),
    ):
        tags.add(ActionTag.THREAT)
    if _contains(
        behavioral_text,
        (r"ладно,? соглаш", r"хорошо,? пусть", r"уступаю", r"без встречн\w* услов\w*"),
    ) and ActionTag.CONDITIONAL_AGREEMENT not in tags:
        tags.add(ActionTag.UNILATERAL_CONCESSION)

    walk_away = _contains(
        behavioral_text,
        (
            r"прекращ\w* переговор",
            r"выхожу из переговор",
            r"сделки не будет",
            r"завершаю переговор",
            r"не будем договариваться",
        ),
    )
    rejected = _contains(
        behavioral_text,
        (r"не соглас\w*", r"не принима\w*", r"отклоня\w*", r"не подходит", r"неприемлем\w*"),
    )
    accepted = _contains(
        behavioral_text,
        (r"\bсогласен\b", r"\bсогласна\b", r"\bпринимаю\b", r"\bдоговорились\b", r"принимаем пакет"),
    )
    if walk_away:
        tags.add(ActionTag.WALK_AWAY)
    elif rejected:
        tags.add(ActionTag.REJECT)
    elif accepted:
        tags.add(ActionTag.ACCEPT)

    sorted_tags = tuple(sorted(tags, key=lambda item: item.value))
    signature_source = "|".join(
        (
            normalized,
            ",".join(item.value for item in sorted_tags),
            ",".join(f"{item.issue_id}={item.value:.6f}" for item in issue_values),
        )
    )
    signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest()
    return ClassifiedAction(
        normalized_text=normalized,
        tags=sorted_tags,
        issue_values=issue_values,
        objective_criterion_ids=criterion_ids,
        signature=signature,
    )

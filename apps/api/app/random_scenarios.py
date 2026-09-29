"""Deterministic, validated scenarios used by the random challenge mode.

The public endpoint chooses a scenario, but never invents deal economics with
an LLM.  Every variant is derived from one of the two battle-tested engine
families and is validated again as a complete ScenarioDefinition.  This keeps
BATNA, reservation points and ZOPA internally consistent while allowing the
catalogue to grow without duplicating large JSON files.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any

from .domain.scenario import ScenarioDefinition


RANDOM_SCENARIO_PREFIX = "random-"

_METHODS_BY_TYPE = {
    "procurement": ["principled_negotiation", "seven_elements", "active_listening", "integrative", "meso", "contingent_agreement"],
    "internal_resources": ["principled_negotiation", "seven_elements", "active_listening", "integrative", "meso"],
    "sales": ["principled_negotiation", "seven_elements", "active_listening", "integrative", "spin", "meso", "contingent_agreement"],
    "partnership": ["principled_negotiation", "seven_elements", "active_listening", "integrative", "meso", "contingent_agreement"],
    "conflict": ["principled_negotiation", "seven_elements", "active_listening", "nvc", "behavioral_change_stairway"],
}


@dataclass(frozen=True)
class RandomVariant:
    id: str
    family: str
    title: str
    summary: str
    situation: str
    objective: str
    participant_role: str
    opponent_role: str
    participant_org: str
    opponent_org: str
    price_factor: float
    tone: str = "businesslike"
    difficulty: str = "intermediate"
    industry: str = "Технологии"
    theme: str = "Закупки"
    negotiation_type: str = "procurement"
    role_tags: tuple[str, ...] = ()
    issue_profile: str = "commercial"


_VARIANTS = (
    RandomVariant(
        id="random-crm-integration",
        family="external",
        title="Внедрение CRM для сети клиник",
        summary="Клиника и интегратор согласуют коммерческие условия запуска единой CRM.",
        situation="Технический объём пилота подтверждён, но до заседания управляющей компании нужно согласовать стоимость, срок, аванс, поддержку и ответственность за задержку.",
        objective="Согласовать жизнеспособный пакет внедрения CRM без срыва запуска филиалов.",
        participant_role="Директор по цифровизации",
        opponent_role="Коммерческий директор интегратора",
        participant_org="Сеть клиник «МедЛайн»",
        opponent_org="ИТ-интегратор «КонтурПро»",
        price_factor=0.62,
        industry="Медицина",
        theme="Закупки",
        role_tags=("заказчик", "поставщик", "цифровизация"),
    ),
    RandomVariant(
        id="random-ev-chargers",
        family="external",
        title="Зарядные станции для бизнес-парка",
        summary="Управляющая компания выбирает условия поставки зарядной инфраструктуры.",
        situation="Площадки подготовлены, оборудование совместимо с сетью, однако стороны ещё не договорились о цене, графике, оплате, гарантии и штрафах.",
        objective="Закрепить надёжные условия поставки и запуска зарядных станций.",
        participant_role="Руководитель инфраструктурных закупок",
        opponent_role="Директор поставщика зарядных станций",
        participant_org="Бизнес-парк «Северный»",
        opponent_org="Компания «ЭнергоТочка»",
        price_factor=1.35,
        difficulty="advanced",
        industry="Недвижимость",
        theme="Закупки",
        role_tags=("закупки", "инфраструктура", "поставщик"),
    ),
    RandomVariant(
        id="random-mobile-app",
        family="external",
        title="Разработка приложения программы лояльности",
        summary="Ритейлер и студия разработки договариваются о выпуске мобильного приложения.",
        situation="Прототип прошёл проверку пользователей. Для старта разработки осталось согласовать бюджет, календарный срок, аванс, гарантийную поддержку и неустойку.",
        objective="Собрать сбалансированный контракт на разработку и поддержку приложения.",
        participant_role="Руководитель продукта",
        opponent_role="Управляющий партнёр студии",
        participant_org="Ритейлер «ГородМаркет»",
        opponent_org="Студия «Пиксель»",
        price_factor=0.48,
        tone="assertive",
        industry="Ритейл",
        theme="Закупки",
        role_tags=("продукт", "подрядчик", "разработка"),
    ),
    RandomVariant(
        id="random-restaurant-equipment",
        family="external",
        title="Оснащение кухни нового ресторана",
        summary="Ресторанная группа и поставщик оборудования готовят контракт к открытию площадки.",
        situation="Планировка кухни утверждена, а дата открытия объявлена. Сторонам нужно договориться о стоимости, поставке, авансе, гарантии и ответственности.",
        objective="Обеспечить открытие ресторана рабочим и защищённым пакетом поставки.",
        participant_role="Операционный директор ресторанной группы",
        opponent_role="Коммерческий директор поставщика",
        participant_org="Ресторанная группа «Терра»",
        opponent_org="Компания «ПрофКухня»",
        price_factor=0.78,
        tone="cooperative",
        industry="HoReCa",
        theme="Закупки",
        role_tags=("операции", "поставщик", "открытие"),
    ),
    RandomVariant(
        id="random-product-launch",
        family="internal",
        title="Команда для запуска нового продукта",
        summary="Продакт-лид защищает ресурсный план запуска перед директором бизнес-направления.",
        situation="Концепция продукта одобрена, но бюджет, состав команды, дата старта и объём отчётности конкурируют с текущими приоритетами бизнеса.",
        objective="Получить достаточные ресурсы и зафиксировать управляемый план запуска продукта.",
        participant_role="Руководитель продукта",
        opponent_role="Директор бизнес-направления",
        participant_org="Компания «Сфера»",
        opponent_org="Компания «Сфера»",
        price_factor=1.18,
        difficulty="advanced",
        industry="Технологии",
        theme="Внутренние ресурсы",
        negotiation_type="internal_resources",
        role_tags=("продукт", "руководство", "команда"),
    ),
    RandomVariant(
        id="random-corporate-academy",
        family="internal",
        title="Запуск корпоративной академии",
        summary="Руководитель обучения согласует ресурсы академии с операционным директором.",
        situation="Программа обучения готова, но компании предстоит определить бюджет пилота, команду, срок начала и формат контроля результата.",
        objective="Согласовать реалистичный ресурсный пакет для пилота корпоративной академии.",
        participant_role="Руководитель корпоративного обучения",
        opponent_role="Операционный директор",
        participant_org="Группа компаний «Вектор»",
        opponent_org="Группа компаний «Вектор»",
        price_factor=0.72,
        tone="cooperative",
        industry="Образование",
        theme="Внутренние ресурсы",
        negotiation_type="internal_resources",
        role_tags=("обучение", "операции", "бюджет"),
    ),
    RandomVariant(
        id="random-regional-office",
        family="internal",
        title="Открытие регионального офиса",
        summary="Руководитель экспансии договаривается о ресурсах для выхода в новый регион.",
        situation="Регион выбран и прогноз продаж подтверждён. До запуска нужно согласовать финансирование, выделенную команду, дату старта и управленческую отчётность.",
        objective="Защитить ресурсы для своевременного и контролируемого открытия офиса.",
        participant_role="Руководитель региональной экспансии",
        opponent_role="Финансовый директор",
        participant_org="Сервисная компания «Маяк»",
        opponent_org="Сервисная компания «Маяк»",
        price_factor=1.42,
        tone="assertive",
        industry="Сервисы",
        theme="Внутренние ресурсы",
        negotiation_type="internal_resources",
        role_tags=("экспансия", "финансы", "команда"),
    ),
    RandomVariant(
        id="random-sustainability-program",
        family="internal",
        title="Программа снижения энергозатрат",
        summary="Менеджер устойчивого развития согласует пилот с директором производства.",
        situation="Аудит выявил потенциал экономии, но пилот требует бюджета, специалистов, окна старта и понятного режима контроля без риска для производства.",
        objective="Получить ресурсы для проверяемого пилота и сохранить операционную устойчивость.",
        participant_role="Менеджер устойчивого развития",
        opponent_role="Директор производства",
        participant_org="Промышленная группа «Орион»",
        opponent_org="Промышленная группа «Орион»",
        price_factor=0.9,
        difficulty="advanced",
        industry="Промышленность",
        theme="Бюджет",
        negotiation_type="internal_resources",
        role_tags=("устойчивость", "производство", "пилот"),
    ),
)


def _library_variant(
    scenario_id: str,
    family: str,
    title: str,
    theme: str,
    industry: str,
    participant_role: str,
    opponent_role: str,
    factor: float,
    *,
    negotiation_type: str,
    difficulty: str = "intermediate",
    tone: str = "businesslike",
    issue_profile: str = "commercial",
) -> RandomVariant:
    """Create a compact catalogue seed; full economics still come from a validated family."""

    return RandomVariant(
        id=scenario_id,
        family=family,
        title=title,
        summary=f"{participant_role} и {opponent_role.lower()} согласуют взаимосвязанный пакет условий.",
        situation=(
            f"Стороны готовы обсуждать «{title.lower()}», но ключевые параметры ещё не собраны "
            "в единый пакет. Нужно согласовать ресурсы, сроки, ответственность и критерии результата."
        ),
        objective=f"Достичь исполнимого соглашения по теме «{title.lower()}» и письменно закрепить обмены.",
        participant_role=participant_role,
        opponent_role=opponent_role,
        participant_org=f"Сторона участника · {industry}",
        opponent_org=f"Сторона оппонента · {industry}",
        price_factor=factor,
        tone=tone,
        difficulty=difficulty,
        industry=industry,
        theme=theme,
        negotiation_type=negotiation_type,
        role_tags=(participant_role.lower(), opponent_role.lower(), theme.lower()),
        issue_profile=issue_profile,
    )


# Together with the two canonical scenarios these seeds form a 30-case library.
# The textual blocks vary, while all hidden economics are inherited, scaled and
# validated as a complete ScenarioDefinition before entering the catalogue.
_VARIANTS += (
    _library_variant("random-saas-renewal", "external", "Продление корпоративной SaaS-лицензии", "Продажи", "Технологии", "ИТ-директор", "Директор по работе с клиентами", 0.55, negotiation_type="sales"),
    _library_variant("random-logistics-contract", "external", "Контракт на региональную логистику", "Продажи", "Логистика", "Директор по цепочке поставок", "Коммерческий директор перевозчика", 1.25, negotiation_type="sales", difficulty="advanced"),
    _library_variant("random-industrial-software", "external", "Поставка промышленного ПО", "Продажи", "Промышленность", "Директор по автоматизации", "Директор по продажам вендора", 0.95, negotiation_type="sales"),
    _library_variant("random-product-salary", "external", "Пересмотр компенсации продакт-менеджера", "Зарплата", "Технологии", "Продакт-менеджер", "Руководитель продукта", 0.18, negotiation_type="partnership", issue_profile="employment"),
    _library_variant("random-engineer-salary", "external", "Компенсация ведущего инженера", "Зарплата", "Промышленность", "Ведущий инженер", "Директор по производству", 0.22, negotiation_type="partnership", difficulty="advanced", issue_profile="employment"),
    _library_variant("random-promotion-package", "external", "Условия повышения руководителя группы", "Зарплата", "Финансы", "Руководитель группы", "Директор департамента", 0.2, negotiation_type="partnership", issue_profile="employment"),
    _library_variant("random-hire-sales-director", "external", "Найм директора по продажам", "Найм", "B2B-сервисы", "Кандидат", "Генеральный директор", 0.28, negotiation_type="partnership", difficulty="advanced", issue_profile="employment"),
    _library_variant("random-hire-plant-engineer", "external", "Найм главного инженера завода", "Найм", "Промышленность", "Кандидат", "HR-директор", 0.25, negotiation_type="partnership", issue_profile="employment"),
    _library_variant("random-contractor-team", "external", "Привлечение команды подрядчика", "Найм", "Разработка", "Руководитель разработки", "Директор кадрового агентства", 0.44, negotiation_type="procurement"),
    _library_variant("random-roadmap-conflict", "internal", "Конфликт приоритетов продуктовой дорожной карты", "Конфликт", "Технологии", "Руководитель продукта", "Руководитель продаж", 0.88, negotiation_type="conflict", tone="assertive"),
    _library_variant("random-service-incident", "internal", "Ответственность после сервисного инцидента", "Конфликт", "Финансы", "Руководитель ИТ", "Директор клиентского сервиса", 0.75, negotiation_type="conflict", difficulty="advanced"),
    _library_variant("random-hybrid-work", "internal", "Правила гибридной работы команды", "Конфликт", "Профессиональные услуги", "Руководитель команды", "HR-бизнес-партнёр", 0.62, negotiation_type="conflict", tone="cooperative"),
    _library_variant("random-co-marketing", "external", "Совместная маркетинговая кампания", "Партнёрство", "Ритейл", "Директор по маркетингу", "Директор партнёрской сети", 0.5, negotiation_type="partnership", issue_profile="partnership"),
    _library_variant("random-joint-warehouse", "external", "Совместный распределительный центр", "Партнёрство", "Логистика", "Операционный директор", "Инвестиционный директор партнёра", 1.6, negotiation_type="partnership", difficulty="advanced", issue_profile="partnership"),
    _library_variant("random-university-lab", "external", "Отраслевая лаборатория с университетом", "Партнёрство", "Образование", "Директор по исследованиям", "Проректор университета", 0.68, negotiation_type="partnership", tone="cooperative", issue_profile="partnership"),
    _library_variant("random-construction-delay", "external", "Перенос срока строительного этапа", "Сроки", "Строительство", "Руководитель проекта заказчика", "Директор генподрядчика", 1.48, negotiation_type="procurement", difficulty="advanced"),
    _library_variant("random-data-migration", "external", "Срок миграции данных", "Сроки", "Финансы", "Директор программы", "Руководитель интегратора", 0.82, negotiation_type="procurement"),
    _library_variant("random-exhibition-launch", "internal", "Подготовка продукта к отраслевой выставке", "Сроки", "Промышленность", "Руководитель запуска", "Директор производства", 0.84, negotiation_type="internal_resources"),
    _library_variant("random-marketing-budget", "internal", "Бюджет квартальной рекламной кампании", "Бюджет", "Ритейл", "Директор по маркетингу", "Финансовый директор", 1.08, negotiation_type="internal_resources"),
    _library_variant("random-cybersecurity-budget", "internal", "Бюджет программы кибербезопасности", "Бюджет", "Финансы", "Директор по информационной безопасности", "Финансовый директор", 1.32, negotiation_type="internal_resources", difficulty="advanced"),
    _library_variant("random-analytics-team", "internal", "Аналитики для коммерческого подразделения", "Внутренние ресурсы", "B2B-сервисы", "Коммерческий директор", "Директор по данным", 0.78, negotiation_type="internal_resources"),
    _library_variant("random-modernization-team", "internal", "Команда модернизации производства", "Внутренние ресурсы", "Промышленность", "Руководитель модернизации", "Операционный директор", 1.26, negotiation_type="internal_resources", difficulty="advanced"),
)


def is_random_scenario_id(scenario_id: str) -> bool:
    return scenario_id.startswith(RANDOM_SCENARIO_PREFIX)


def random_variant_metadata(scenario_id: str) -> dict[str, Any] | None:
    variant = next((item for item in _VARIANTS if item.id == scenario_id), None)
    if variant is None:
        return None
    return {
        "industry": variant.industry,
        "theme": variant.theme,
        "negotiation_type": variant.negotiation_type,
        "role_tags": variant.role_tags,
    }


def _scale_issue(payload: dict[str, Any], issue_id: str, factor: float) -> None:
    issue = next(item for item in payload["issues"] if item["id"] == issue_id)
    for ranges in issue["party_ranges"].values():
        for key in ("minimum", "maximum", "reservation", "aspiration"):
            ranges[key] = round(float(ranges[key]) * factor, 2)
    zopa = next(item for item in payload["zopa"] if item["issue_id"] == issue_id)
    if zopa["status"] == "overlap":
        zopa["lower"] = round(float(zopa["lower"]) * factor, 2)
        zopa["upper"] = round(float(zopa["upper"]) * factor, 2)
    for offer in payload["offer_templates"]:
        if issue_id in offer["values"]:
            offer["values"][issue_id] = round(float(offer["values"][issue_id]) * factor, 2)


def _common_identity(payload: dict[str, Any], variant: RandomVariant) -> None:
    payload["metadata"].update(
        {
            "id": variant.id,
            "version_id": f"{variant.id}:v1",
        }
    )
    payload["public_briefing"].update(
        {
            "title": variant.title,
            "summary": variant.summary,
            "situation": variant.situation,
            "objective": variant.objective,
            "known_facts": [
                "Стороны подтвердили заинтересованность в результате, но ещё не согласовали полный пакет условий.",
                "У каждой стороны есть рабочая альтернатива на случай отсутствия соглашения.",
                "Решение должно опираться на измеримые условия и взаимные обязательства.",
            ],
        }
    )
    participant, opponent = payload["roles"]
    participant.update(
        {
            "title": variant.participant_role,
            "organization": variant.participant_org,
            "goal": variant.objective,
            "aspiration": "Добиться сильного пакета по всем ключевым вопросам, сохранив рабочие отношения.",
            "reservation": "Не принимать итоговый пакет за пределами утверждённых финансовых и операционных границ.",
            "authority": "Может согласовать пакет в пределах утверждённых границ и обменивать условия между собой.",
        }
    )
    opponent.update(
        {
            "title": variant.opponent_role,
            "organization": variant.opponent_org,
            "goal": "Защитить ресурсы своей стороны и получить измеримые встречные обязательства.",
            "aspiration": "Получить выгодный пакет и снизить риски исполнения договорённостей.",
            "reservation": "Не принимать пакет, который хуже доступной альтернативы или создаёт неконтролируемые риски.",
            "authority": "Может согласовать пакет в пределах своих полномочий при наличии встречных условий.",
        }
    )
    participant["batna"]["description"] = "Перейти к сокращённому варианту инициативы с более поздним результатом и меньшим эффектом."
    opponent["batna"]["description"] = "Сохранить ресурсы для другой приоритетной сделки или инициативы."
    payload["tone"] = variant.tone
    payload["difficulty"] = variant.difficulty
    payload["negotiation_type"] = variant.negotiation_type
    payload["methodology_modules"] = _METHODS_BY_TYPE[variant.negotiation_type]


def _external_payload(base: ScenarioDefinition, variant: RandomVariant) -> dict[str, Any]:
    payload = deepcopy(base.model_dump(mode="json"))
    _common_identity(payload, variant)
    _scale_issue(payload, "price", variant.price_factor)
    payload["public_briefing"]["agenda"] = [
        "Стоимость", "Срок готовности", "Предоплата", "Гарантийная поддержка", "Ответственность за задержку"
    ]
    titles = {
        "price": ("Стоимость контракта", "Полная стоимость работ, поставки и запуска."),
        "delivery_days": ("Срок готовности", "Число календарных дней до готовности результата."),
        "prepayment": ("Предоплата", "Доля стоимости, перечисляемая после подписания договора."),
        "warranty_months": ("Гарантийная поддержка", "Срок устранения гарантийных недостатков без доплаты."),
        "delay_penalty": ("Штраф за задержку", "Ответственность исполнителя за каждый день просрочки."),
    }
    for issue in payload["issues"]:
        issue["title"], issue["description"] = titles[issue["id"]]
    if variant.issue_profile == "employment":
        employment = {
            "price": ("Годовая компенсация", "Фиксированная часть годового компенсационного пакета.", "рублей"),
            "delivery_days": ("Дата выхода", "Число календарных дней до выхода в новой роли.", "дней"),
            "prepayment": ("Стартовый бонус", "Стартовый бонус как доля годовой компенсации.", "процентов"),
            "warranty_months": ("Пересмотр условий", "Срок до формального пересмотра роли и компенсации.", "месяцев"),
            "delay_penalty": ("Переменная часть", "Целевой годовой бонус за измеримый результат.", "процентов"),
        }
        for issue in payload["issues"]:
            issue["title"], issue["description"], issue["unit"] = employment[issue["id"]]
        payload["public_briefing"]["agenda"] = [item[0] for item in employment.values()]
    elif variant.issue_profile == "partnership":
        partnership = {
            "price": ("Вклад сторон", "Совокупный денежный и ресурсный вклад в партнёрство.", "рублей"),
            "delivery_days": ("Срок запуска", "Число дней до совместного запуска.", "дней"),
            "prepayment": ("Первоначальное финансирование", "Доля вклада, доступная на старте.", "процентов"),
            "warranty_months": ("Горизонт обязательств", "Срок взаимных обязательств сторон.", "месяцев"),
            "delay_penalty": ("Доля результата", "Доля экономического результата партнёра.", "процентов"),
        }
        for issue in payload["issues"]:
            issue["title"], issue["description"], issue["unit"] = partnership[issue["id"]]
        payload["public_briefing"]["agenda"] = [item[0] for item in partnership.values()]
    payload["roles"][0]["explicit_interests"][0]["description"] = "Получить результат в согласованный срок и без скрытых расходов."
    payload["roles"][0]["explicit_interests"][1]["description"] = "Сохранить предсказуемую нагрузку на денежный поток."
    payload["roles"][1]["explicit_interests"][0]["description"] = "Сохранить экономику и управляемость исполнения контракта."
    payload["roles"][1]["explicit_interests"][1]["description"] = "Надёжно закрепить производственный или проектный слот."
    payload["roles"][0]["hidden_interests"][0]["description"] = "Внутренний контроль отдельно проверит длительность гарантийной поддержки."
    payload["roles"][0]["hidden_interests"][1]["description"] = "Успешный запуск откроет путь к следующему этапу программы."
    payload["roles"][1]["hidden_interests"][0]["description"] = "Достаточный аванс снижает риск кассового разрыва в начале исполнения."
    payload["roles"][1]["hidden_interests"][1]["description"] = "Успешный проект важен как отраслевой референс."
    payload["disclosure_rules"][0]["reveal_message"] = "Для уверенного старта исполнения нам важен достаточный аванс."
    payload["disclosure_rules"][1]["reveal_message"] = "Гарантийный срок будет отдельно проверяться внутренним контролем."
    return payload


def _internal_payload(base: ScenarioDefinition, variant: RandomVariant) -> dict[str, Any]:
    payload = deepcopy(base.model_dump(mode="json"))
    _common_identity(payload, variant)
    _scale_issue(payload, "budget", variant.price_factor)
    payload["public_briefing"]["agenda"] = [
        "Бюджет", "Команда", "Срок начала", "Формат контроля"
    ]
    payload["roles"][0]["explicit_interests"][0]["description"] = "Получить проверяемый результат инициативы в текущем плановом периоде."
    payload["roles"][0]["explicit_interests"][1]["description"] = "Сформировать устойчивую команду без постоянных переработок."
    payload["roles"][1]["explicit_interests"][0]["description"] = "Не сорвать действующие обязательства подразделения."
    payload["roles"][1]["explicit_interests"][1]["description"] = "Получать прозрачные показатели прогресса и использования ресурсов."
    payload["roles"][0]["hidden_interests"][0]["description"] = "Первую версию можно сузить без потери проверяемой ценности пилота."
    payload["roles"][0]["hidden_interests"][1]["description"] = "Успешный пилот влияет на будущий статус инициативы в компании."
    payload["roles"][1]["hidden_interests"][0]["description"] = "Скоро потребуется представить руководству измеримый статус портфеля инициатив."
    payload["roles"][1]["hidden_interests"][1]["description"] = "Ключевых сотрудников нельзя надолго отвлекать от текущих обязательств."
    payload["disclosure_rules"][0]["reveal_message"] = "Скоро руководству потребуется показать измеримый статус портфеля."
    payload["disclosure_rules"][1]["reveal_message"] = "Для проверки гипотезы полный объём на первом запуске не обязателен."
    return payload


def build_random_scenarios(
    definitions: tuple[ScenarioDefinition, ...],
) -> tuple[ScenarioDefinition, ...]:
    """Build the curated random pool when both canonical engine families exist."""

    by_id = {item.metadata.id: item for item in definitions}
    external = by_id.get("equipment-supply")
    internal = by_id.get("project-resources")
    if external is None or internal is None:
        return ()

    result: list[ScenarioDefinition] = []
    for variant in _VARIANTS:
        payload = (
            _external_payload(external, variant)
            if variant.family == "external"
            else _internal_payload(internal, variant)
        )
        result.append(
            ScenarioDefinition.model_validate_json(
                json.dumps(payload, ensure_ascii=False)
            )
        )
    return tuple(result)


__all__ = [
    "RANDOM_SCENARIO_PREFIX",
    "build_random_scenarios",
    "is_random_scenario_id",
    "random_variant_metadata",
]

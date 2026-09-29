import type { ChatMessage, Report, Scenario } from "./types";

export const demoScenarios: Scenario[] = [
  {
    id: "equipment-supply",
    title: "Поставка оборудования",
    subtitle: "Закупки · средняя сложность",
    description: "Согласуйте поставку линии фасовки на условиях, выгодных обеим сторонам.",
    role: "Руководитель закупок",
    opponent: "Коммерческий директор поставщика",
    duration: "10–12 минут",
    skills: ["BATNA и ZOPA", "объективные критерии", "варианты сделки"],
    objective: "Собрать устойчивый пакет условий по цене, сроку, оплате, гарантии и ответственности сторон.",
    context: "Покупатель и поставщик согласовали техническую конфигурацию, но должны договориться о коммерческих условиях до плановой модернизации цеха.",
    tasks: [
      { id: "outcome.agreement", title: "Зафиксировать полный и жизнеспособный пакет условий", description: "Соглашение должно охватывать все предметы переговоров." },
      { id: "issue.price", title: "Цена контракта: не более 10 млн рублей", description: "Не выходите за предел полномочий покупателя." },
      { id: "issue.delivery_days", title: "Срок поставки: не более 45 дней", description: "Сохраните график модернизации." },
      { id: "issue.prepayment", title: "Предоплата: не более 50%", description: "Не создавайте чрезмерную нагрузку на оборотный капитал." },
      { id: "issue.warranty_months", title: "Гарантия: не менее 24 месяцев", description: "Защитите эксплуатационный риск." },
      { id: "issue.delay_penalty", title: "Штраф за задержку: не менее 0,2% в день", description: "Зафиксируйте измеримую ответственность за срок." },
    ],
  },
  {
    id: "project-resources",
    title: "Ресурсы для проекта",
    subtitle: "Внутренние переговоры · средняя сложность",
    description: "Договоритесь о выделении команды аналитиков для запуска нового сервиса.",
    role: "Руководитель проекта",
    opponent: "Директор по продукту",
    duration: "8–10 минут",
    skills: ["интересы вместо позиций", "активное слушание", "фиксация обязательств"],
    objective: "Добиться реалистичного ресурсного пакета и согласовать измеримые обязательства сторон.",
    context: "Совет директоров одобрил направление проекта, однако бюджет, команда, срок старта и формат контроля ещё не утверждены.",
    tasks: [
      { id: "outcome.agreement", title: "Зафиксировать полный и жизнеспособный ресурсный пакет", description: "Согласуйте бюджет, команду, старт и контроль." },
      { id: "issue.budget", title: "Бюджет проекта: не менее 5,5 млн рублей", description: "Сохраните минимальную экономику пилота." },
      { id: "issue.specialists", title: "Выделенные специалисты: не менее 3 человек", description: "Обеспечьте устойчивую рабочую команду." },
      { id: "issue.start_days", title: "Срок начала: не более 30 дней", description: "Не сорвите проверяемый запуск." },
      { id: "issue.reporting_hours", title: "Управленческая отчётность: не более 5 часов в неделю", description: "Сохраните разумную нагрузку команды." },
    ],
  },
];

const openingMessages: Record<string, string> = {
  "equipment-supply": "Добрый день. Наша стартовая позиция — 10,8 млн рублей и поставка за 50 дней. Если вам нужен другой срок или цена, давайте обсудим встречные условия по всему пакету.",
  "project-resources": "Добрый день. На пилот сейчас могу предложить 4 млн рублей и двух специалистов. Чтобы выделить больше, нужно договориться, как не сорвать текущие программы.",
};

export function initialMessagesForScenario(scenarioId: string, negotiationType?: string): ChatMessage[] {
  const genericOpening = negotiationType === "internal_resources"
    ? "Добрый день. Бюджет и команда у нас ограничены текущими обязательствами. Обсудим, какие условия позволят выделить ресурсы на вашу инициативу."
    : "Добрый день. По стоимости и срокам у нас пока жёсткая стартовая позиция. Давайте посмотрим, где возможен взаимный обмен условиями.";
  return [
    { id: `${scenarioId}-system`, author: "system", text: "Сессия началась. Сообщения будут сохранены для итогового разбора.", timestamp: "сейчас" },
    {
      id: `${scenarioId}-opener`,
      author: "opponent",
      text: openingMessages[scenarioId] ?? genericOpening,
      timestamp: "сейчас",
    },
  ];
}

export const demoReport: Report = {
  sessionId: "demo-session", scenarioId: "equipment-supply", scenarioVersionId: "v1", rubricVersion: "0.1", evaluatorVersion: "demo", status: "completed", score: 74, level: "working", label: "Рабочий результат с зонами улучшения",
  summary: "Вы начали с выяснения ограничений и удержали деловой тон. Для сильного результата осталось перевести интересы сторон в конкретный пакет условий.",
  outcome: { kind: "agreement", label: "Есть основа для соглашения", description: "Стороны приблизились к рабочему варианту, но обязательства стоит зафиксировать точнее.", participantUtility: null, batnaUtility: null, meetsBatna: true, reservationRespected: true, acceptedTerms: ["Срок поставки обсуждён", "Гарантийные условия обозначены"] },
  blocks: ["P", "C", "V", "R", "T"].map((id, index) => ({ id, title: ["Подготовка и интересы", "Качество процесса", "Создание ценности", "Качество результата", "Отношения и тон"][index], score: [15, 19, 14, 17, 9][index], maxScore: [20, 25, 20, 25, 10][index], explanation: "Есть подтверждённые действия; часть критериев можно усилить.", criteria: [{ id: `${id}1`, title: "Наблюдаемый критерий", score: [15, 19, 14, 17, 9][index], maxScore: [20, 25, 20, 25, 10][index], explanation: "Подтверждено репликой диалога.", evidence: [{ messageId: "demo-1", turn: 2, quote: "Давайте уточним, что для вас критично в этом условии." }] }] })),
  penalties: [],
  strengths: [{ code: "I1", title: "Исследование интереса", explanation: "Открытый вопрос помог выявить интерес оппонента.", points: 4, evidence: [{ messageId: "demo-1", turn: 2, quote: "Давайте уточним, что для вас критично в этом условии." }] }, { code: "I3", title: "Активное слушание", explanation: "Коммуникация оставалась уважительной и предметной.", points: 4, evidence: [{ messageId: "demo-2", turn: 4, quote: "Правильно понимаю, что срок важнее объёма?" }] }],
  improvements: [{ priority: 1, title: "Свяжите уступку с встречным условием", originalQuote: null, suggestedText: "Готовы обсудить срок, если зафиксируем гарантию и этап оплаты.", rationale: "Так обмен становится взаимным и измеримым.", indicatorId: "I7" }],
  taskChecks: [
    { id: "outcome.agreement", title: "Зафиксировать полный и жизнеспособный пакет условий", status: "met", explanation: "Соглашение подтверждено.", acceptedValue: null },
    { id: "issue.price", title: "Цена контракта: не более 10 млн рублей", status: "met", explanation: "Цена находится в допустимой границе.", acceptedValue: "9,8 млн рублей" },
    { id: "issue.delivery_days", title: "Срок поставки: не более 45 дней", status: "not_met", explanation: "Срок не был зафиксирован достаточно точно.", acceptedValue: null },
  ],
  coaching: { provider: "deterministic", model: null, fallback: true, reason: "not_configured", summary: "Для более сильного результата свяжите уступку со встречным условием и зафиксируйте весь пакет.", points: [{ turn: 2, quote: "Давайте уточним, что для вас критично в этом условии.", problem: "Вопрос выявляет интерес, но после него не сформулирован измеримый обмен.", betterApproach: "Связать уступку по сроку с гарантией и оплатой.", suggestedText: "Готовы обсудить срок, если зафиксируем гарантию 24 месяца и предоплату не выше 50%." }] },
  trajectory: [{ turn: 1, trust: 48, tension: 32, progress: 22, relationship: 52 }, { turn: 3, trust: 61, tension: 28, progress: 48, relationship: 63 }, { turn: 5, trust: 72, tension: 20, progress: 74, relationship: 76 }],
  methodology: { rubricVersion: "0.1", formula: "Final = clamp(0, 100, Raw + penalties)", rawScore: 74, penaltyPoints: 0, scoreCap: null, disclaimer: "Методика версии 0.1 является гипотезой и требует экспертной калибровки." },
  simulation: null,
  nextStep: "Сформулируйте 2–3 варианта обмена: срок ↔ объём заказа, предоплата ↔ гарантия, цена ↔ сервис.",
};

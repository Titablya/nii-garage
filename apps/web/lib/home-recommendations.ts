import type { LearningDashboard, Scenario, SkillProgress } from "./types";

export type GuestPractice = { sessionId: string; scenarioId: string; score: number; completedAt: string };
export type TopicAdvice = { scenario: Scenario; reason: string; focus: string };
export type TopicAdviceSet = { kind: "account" | "device" | "starter"; items: TopicAdvice[] };

const STARTER_IDS = ["project-resources", "equipment-supply", "random-roadmap-conflict"];
const SKILL_METHODS: Record<string, string[]> = {
  interests: ["principled_negotiation", "integrative"],
  questions: ["spin", "active_listening"],
  active_listening: ["active_listening", "nvc"],
  criteria: ["seven_elements", "principled_negotiation"],
  meso: ["meso", "integrative"],
  exchanges: ["contingent_agreement", "integrative"],
  batna: ["distributive", "seven_elements"],
  commitments: ["contingent_agreement", "seven_elements"],
};

export function parseGuestPractice(value: unknown): GuestPractice[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is GuestPractice =>
    typeof item?.sessionId === "string" && typeof item.scenarioId === "string"
    && typeof item.score === "number" && Number.isFinite(item.score)
    && item.score >= 0 && item.score <= 100 && typeof item.completedAt === "string",
  ).slice(-24);
}

export function addGuestPractice(current: GuestPractice[], entry: GuestPractice): GuestPractice[] {
  return [...current.filter((item) => item.sessionId !== entry.sessionId), entry].slice(-24);
}

function uniqueCatalog(scenarios: Scenario[]): Scenario[] {
  return [...new Map(scenarios.filter((item) => item.source !== "custom").map((item) => [item.id, item])).values()];
}

function starterAdvice(catalog: Scenario[], first?: Scenario): TopicAdvice[] {
  const ordered = [first, ...STARTER_IDS.map((id) => catalog.find((item) => item.id === id)), ...catalog]
    .filter((item): item is Scenario => Boolean(item));
  const chosen: TopicAdvice[] = [];
  for (const scenario of ordered) {
    if (chosen.some((item) => item.scenario.id === scenario.id)) continue;
    if (chosen.length > 1 && chosen.some((item) => item.scenario.theme === scenario.theme)) continue;
    chosen.push({ scenario, focus: scenario.theme || "Практика", reason: "Стартовая диагностика: попробуйте новый переговорный контекст. После завершённой сессии советы станут точнее." });
    if (chosen.length === 3) break;
  }
  return chosen;
}

function findForSkill(catalog: Scenario[], selected: TopicAdvice[], skill: SkillProgress, practiced: Map<string, number>): Scenario | null {
  const methods = SKILL_METHODS[skill.id] ?? [];
  const candidates = catalog.filter((item) => !selected.some((chosen) => chosen.scenario.id === item.id));
  const ranked = candidates.map((item) => {
    const match = methods.some((method) => item.methods?.includes(method));
    const repeatedTheme = selected.some((chosen) => chosen.scenario.theme && chosen.scenario.theme === item.theme);
    const attempts = practiced.get(item.id) ?? 0;
    return { item, rank: (match ? 50 : 0) + (attempts === 0 ? 18 : 0) + (repeatedTheme ? 0 : 12) - Math.min(attempts, 8) * 3 };
  });
  ranked.sort((a, b) => b.rank - a.rank || a.item.title.localeCompare(b.item.title, "ru"));
  return ranked[0]?.item ?? null;
}

export function buildTopicAdvice(scenarios: Scenario[], dashboard: LearningDashboard | null, guestPractice: GuestPractice[], authenticated: boolean): TopicAdviceSet {
  const catalog = uniqueCatalog(scenarios);
  if (!catalog.length) return { kind: "starter", items: [] };

  if (authenticated && dashboard) {
    const primary = catalog.find((item) => item.id === dashboard.recommendation.scenarioId) ?? catalog[0];
    const selected: TopicAdvice[] = [{ scenario: primary, focus: dashboard.skillMap.find((item) => item.id === dashboard.recommendation.skillId)?.title ?? "Личная цель", reason: dashboard.recommendation.reason }];
    const practiced = new Map(dashboard.scenarioProgress.map((item) => [item.scenarioId, item.attempts]));
    const skills = [...dashboard.skillMap].sort((a, b) => {
      if (a.id === dashboard.goal?.skillId) return -1;
      if (b.id === dashboard.goal?.skillId) return 1;
      if (a.due !== b.due) return a.due ? -1 : 1;
      return (a.score ?? 100) - (b.score ?? 100) || a.id.localeCompare(b.id);
    });
    for (const skill of skills) {
      if (selected.length === 3) break;
      const scenario = findForSkill(catalog, selected, skill, practiced);
      if (!scenario) break;
      const score = skill.score === null ? "пока не измерен" : `${skill.score}/100`;
      selected.push({ scenario, focus: skill.title, reason: `Навык «${skill.title}» — ${score}. Попробуйте этот контекст, чтобы проверить его в новой ситуации.` });
    }
    return { kind: dashboard.comparableSessions ? "account" : "starter", items: selected };
  }

  if (!authenticated && guestPractice.length) {
    const recent = [...guestPractice].sort((a, b) => b.completedAt.localeCompare(a.completedAt));
    const latest = recent[0];
    const lastScenario = catalog.find((item) => item.id === latest.scenarioId) ?? null;
    const practiced = new Map<string, number>();
    for (const item of recent) practiced.set(item.scenarioId, (practiced.get(item.scenarioId) ?? 0) + 1);
    const selected: TopicAdvice[] = [];
    if (lastScenario && latest.score < 75) selected.push({ scenario: lastScenario, focus: "Закрепить результат", reason: `В последней попытке вы набрали ${latest.score}/100. Повторите тему и попробуйте улучшить итог.` });
    const ordered = [...catalog].sort((a, b) => {
      const aRank = (practiced.get(a.id) ?? 0) * 10 + (a.theme === lastScenario?.theme ? 1 : 0);
      const bRank = (practiced.get(b.id) ?? 0) * 10 + (b.theme === lastScenario?.theme ? 1 : 0);
      return aRank - bRank || a.title.localeCompare(b.title, "ru");
    });
    for (const scenario of ordered) {
      if (selected.length === 3) break;
      if (selected.some((item) => item.scenario.id === scenario.id)) continue;
      if (selected.some((item) => item.scenario.theme && item.scenario.theme === scenario.theme)) continue;
      selected.push({ scenario, focus: "Новая тема", reason: `После темы «${lastScenario?.title ?? "предыдущей тренировки"}» полезно потренироваться в другом контексте. Подбор учитывает ваши попытки в этом браузере.` });
    }
    return { kind: "device", items: selected };
  }

  return { kind: "starter", items: starterAdvice(catalog, authenticated && dashboard ? catalog.find((item) => item.id === dashboard.recommendation.scenarioId) : undefined) };
}

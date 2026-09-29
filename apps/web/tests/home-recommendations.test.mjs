import assert from "node:assert/strict";
import test from "node:test";
import { addGuestPractice, buildTopicAdvice, parseGuestPractice } from "../lib/home-recommendations.ts";

const scenarios = [
  { id: "project-resources", title: "Ресурсы проекта", theme: "Команда", methods: ["spin"] },
  { id: "equipment-supply", title: "Поставка оборудования", theme: "Закупки", methods: ["meso"] },
  { id: "random-roadmap-conflict", title: "Спор о плане", theme: "Продукт", methods: ["active_listening"] },
  { id: "another-supply", title: "Другая поставка", theme: "Закупки", methods: ["contingent_agreement"] },
];

test("new users see an explicitly labelled starter selection", () => {
  const result = buildTopicAdvice(scenarios, null, [], false);
  assert.equal(result.kind, "starter");
  assert.equal(result.items.length, 3);
  assert.equal(new Set(result.items.map((item) => item.scenario.id)).size, 3);
});

test("guest advice follows the actual last completed score and avoids repeated themes", () => {
  const attempts = [{ sessionId: "session-1", scenarioId: "equipment-supply", score: 61, completedAt: "2026-09-25T10:00:00Z" }];
  const result = buildTopicAdvice(scenarios, null, attempts, false);
  assert.equal(result.kind, "device");
  assert.equal(result.items[0].scenario.id, "equipment-supply");
  assert.match(result.items[0].reason, /61\/100/);
  assert.equal(new Set(result.items.map((item) => item.scenario.theme)).size, result.items.length);
});

test("account advice prioritizes the user's recommendation and weak skills", () => {
  const dashboard = {
    comparableSessions: 3,
    goal: { skillId: "questions" },
    recommendation: { skillId: "questions", scenarioId: "project-resources", reason: "Отработайте открытые вопросы" },
    skillMap: [
      { id: "questions", title: "Вопросы", score: 43, due: true },
      { id: "meso", title: "Варианты", score: 55, due: false },
    ],
    scenarioProgress: [{ scenarioId: "project-resources", attempts: 2 }],
  };
  const result = buildTopicAdvice(scenarios, dashboard, [], true);
  assert.equal(result.kind, "account");
  assert.equal(result.items[0].scenario.id, "project-resources");
  assert.equal(result.items[0].reason, "Отработайте открытые вопросы");
  assert.equal(new Set(result.items.map((item) => item.scenario.id)).size, result.items.length);
});

test("local history rejects malformed entries and deduplicates a completed session", () => {
  const entry = { sessionId: "one", scenarioId: "equipment-supply", score: 72, completedAt: "2026-09-25T10:00:00Z" };
  assert.deepEqual(parseGuestPractice([entry, { ...entry, score: "bad" }, null]), [entry]);
  assert.deepEqual(addGuestPractice([entry], { ...entry, score: 79 }), [{ ...entry, score: 79 }]);
});

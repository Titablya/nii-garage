import assert from "node:assert/strict";
import test from "node:test";
import { CallTurnPolicy, combineRecognitionSegments } from "../lib/call-turn-policy.ts";

test("short greeting remains pending through a natural pause", () => {
  const policy = new CallTurnPolicy();
  policy.updateRecognition("Добрый день", 1000);
  assert.equal(policy.takeIfReady(2200), null);
  assert.equal(policy.takeIfReady(20000), null);
  policy.updateRecognition("Добрый день. Мне важно обсудить сроки поставки", 20050);
  assert.equal(policy.takeIfReady(21600), null);
  assert.equal(policy.takeIfReady(21950), "Добрый день. Мне важно обсудить сроки поставки");
});

test("mic activity extends a pending turn even after STT finalizes a segment", () => {
  const policy = new CallTurnPolicy();
  policy.updateRecognition("Давайте обсудим поставку завтра", 1000);
  policy.noteMicActivity(2750);
  assert.equal(policy.takeIfReady(3000), null);
  assert.equal(policy.takeIfReady(4650), "Давайте обсудим поставку завтра");
});

test("restart preserves pending speech and deduplicates a repeated prefix", () => {
  const policy = new CallTurnPolicy();
  policy.updateRecognition("Добрый день", 1000);
  const combined = combineRecognitionSegments(policy.pending, "Добрый день, я хотел уточнить условия оплаты");
  policy.updateRecognition(combined, 1500);
  assert.equal(policy.pending, "Добрый день я хотел уточнить условия оплаты");
  assert.equal(policy.takeIfReady(3400), "Добрый день я хотел уточнить условия оплаты");
});

test("manual end can send a short reply without waiting for silence timer", () => {
  const policy = new CallTurnPolicy();
  policy.updateRecognition("Согласен", 1000);
  assert.equal(policy.takeIfReady(1200), null);
  assert.equal(policy.takeNow(), "Согласен");
  assert.equal(policy.takeIfReady(5000), null);
});

test("greeting alone can still be sent explicitly", () => {
  const policy = new CallTurnPolicy();
  policy.updateRecognition("Здравствуйте", 1000);
  assert.equal(policy.takeIfReady(30000), null);
  assert.equal(policy.takeNow(), "Здравствуйте");
});

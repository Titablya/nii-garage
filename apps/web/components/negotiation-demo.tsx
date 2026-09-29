"use client";

import { createContext, FormEvent, KeyboardEvent, ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";
import { HeroConversationPreview, TrainingFlow } from "./negotiation-visuals";
import { appealPeerReview, checkSimulationHypothesis, completeAndGetReport, completeLearningDrill, completePersonalizedDrill, createSession, createMotivationTeam, deleteAccount, deleteVoiceRecording, getAccountHistory, getAdaptiveCoachSummary, getAttemptComparison, getCoachPrebrief, getCurrentAccount, getLearningDashboard, getMotivationDashboard, getNextPeerReview, getPeerReviewStatus, getPersonalizedDrill, getRandomScenario, getScenario, getScenarioCatalog, getScenarioDrafts, getScenarios, getSession, getVoiceRecordings, joinMotivationTeam, leaveMotivationTeam, loginAccount, logoutAccount, recoverAccount, registerAccount, requestCoachHint, requestCoachRewrite, retrySession, saveCoachPrebrief, saveLearningGoal, saveMotivationPreferences, saveScenarioDraft, sendSessionMessage, startMotivationChallenge, submitPeerReview, suggestScenarioText, uploadVoiceRecording } from "../lib/api";
import { LiveConversation } from "./live-conversation";
import { CallConversation } from "./call-conversation";
import { demoReport, initialMessagesForScenario } from "../lib/demo-data";
import { addGuestPractice, buildTopicAdvice, parseGuestPractice, type GuestPractice } from "../lib/home-recommendations";
import type { AccountHistory, AccountHistoryItem, AccountProfile, AdaptiveCoachSummary, AdaptiveDrillFeedback, AttemptComparison, AttemptSnapshot, ChatMessage, CoachHint, CoachRewrite, CoachSkillId, HistoricalAttemptComparison, LearningDashboard, MessageResult, MotivationDashboard, PeerReviewAssignment, PeerReviewDraftItem, PeerReviewResult, PeerReviewSessionStatus, PersonalizedMiniDrill, PrebriefWorksheet, PrebriefWorksheetInput, Report as ReportData, Scenario, ScenarioDraft, ScenarioDraftInput, SessionConfiguration, SimulationSnapshot, VoiceDraft, VoiceRecording } from "../lib/types";

type Step = "choose" | "library" | "builder" | "random" | "configure" | "brief" | "prebrief" | "chat" | "report" | "peer" | "peer_result" | "comparison" | "auth" | "profile";
type EntryMode = "ready" | "custom" | "random";
type ConversationFormat = "call" | "text";
type StoredSessionPointer = { sessionId: string; scenarioId: string; topic: string; attemptNumber: number; format?: ConversationFormat; entryMode?: EntryMode };
type AccountNavigation = { account: AccountProfile | null; openAuth: () => void; openProfile: () => void };
const AccountNavigationContext = createContext<AccountNavigation>({ account: null, openAuth: () => undefined, openProfile: () => undefined });
const activeSessionKey = "negotiation-arena.active-session.v1";
const conversationFormatKey = "negotiation-arena.conversation-format.v1";
const guestPracticeKey = "negotiation-arena.guest-practice.v1";
const defaultConfiguration = (scenario: Scenario): SessionConfiguration => ({ topic: scenario.title, context: scenario.context, participantRole: scenario.role, opponentRole: scenario.opponent, objective: scenario.objective, difficulty: scenario.difficulty ?? "medium", tone: scenario.tone ?? "businesslike", maxTurns: scenario.maxTurns ?? 12, simulation: { enabled: true, mode: "meeting", opponentStrategy: "analytical", aiParticipants: 1, eventIntensity: 1, decisionTimeSeconds: 90, seed: null } });
const difficultyOptions = [
  { value: "easy", label: "Поддерживающая", description: "Оппонент охотнее раскрывает интересы и спокойнее реагирует на ошибки." },
  { value: "medium", label: "Сбалансированная", description: "Реалистичное сопротивление и пространство для взаимовыгодного решения." },
  { value: "hard", label: "Требовательная", description: "Меньше доверия на старте, выше напряжение и цена неточных формулировок." },
] as const;
const toneOptions = [
  { value: "cooperative", label: "Партнёрский", description: "Мягкий, открытый к совместному поиску вариантов." },
  { value: "businesslike", label: "Деловой", description: "Спокойный и предметный, без лишних уступок." },
  { value: "firm", label: "Жёсткий", description: "Прямой, требовательный и настойчивый, но без токсичности." },
] as const;
const difficultyLabel = Object.fromEntries(difficultyOptions.map((item) => [item.value, item.label])) as Record<SessionConfiguration["difficulty"], string>;
const toneLabel = Object.fromEntries(toneOptions.map((item) => [item.value, item.label])) as Record<SessionConfiguration["tone"], string>;
const coachSkillOptions: Array<{ value: CoachSkillId; label: string; cue: string }> = [
  { value: "interests", label: "Интересы", cue: "отделить позицию от причин" },
  { value: "questions", label: "Вопросы", cue: "получать новую информацию" },
  { value: "active_listening", label: "Активное слушание", cue: "проверять понимание" },
  { value: "criteria", label: "Объективные критерии", cue: "опираться на проверяемые ориентиры" },
  { value: "meso", label: "MESO", cue: "сравнивать несколько пакетов" },
  { value: "exchanges", label: "Взаимные обмены", cue: "связывать уступку с условием" },
  { value: "batna", label: "BATNA и границы", cue: "не соглашаться хуже альтернативы" },
  { value: "commitments", label: "Фиксация", cue: "закреплять кто, что и когда" },
];
const coachSkillLabel = Object.fromEntries(coachSkillOptions.map((item) => [item.value, item.label])) as Record<CoachSkillId, string>;
const createMessageId = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
  ? crypto.randomUUID()
  : `message-${Date.now()}-${Math.random().toString(36).slice(2)}`;

function readStoredSession(): StoredSessionPointer | null {
  try {
    const value = window.localStorage.getItem(activeSessionKey);
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<StoredSessionPointer>;
    if (typeof parsed.sessionId !== "string" || typeof parsed.scenarioId !== "string" || typeof parsed.topic !== "string" || typeof parsed.attemptNumber !== "number") return null;
    return parsed as StoredSessionPointer;
  } catch {
    return null;
  }
}

function storeActiveSession(pointer: StoredSessionPointer | null) {
  try {
    if (pointer) window.localStorage.setItem(activeSessionKey, JSON.stringify(pointer));
    else window.localStorage.removeItem(activeSessionKey);
  } catch {
    // Private browsing or a strict storage policy must not block training.
  }
}

export function NegotiationDemo() {
  const [step, setStep] = useState<Step>("choose");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [randomScenario, setRandomScenario] = useState<Scenario | null>(null);
  const [randomStatus, setRandomStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [randomNotice, setRandomNotice] = useState("");
  const [catalogScenarios, setCatalogScenarios] = useState<Scenario[]>([]);
  const [catalogStatus, setCatalogStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [catalogNotice, setCatalogNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string>("");
  const [entryMode, setEntryMode] = useState<EntryMode>("ready");
  const [briefOrigin, setBriefOrigin] = useState<"choose" | "configure" | "library" | "builder" | "random">("choose");
  const [conversationFormat, setConversationFormat] = useState<ConversationFormat>("call");
  const [configuration, setConfiguration] = useState<SessionConfiguration | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "fallback" | "error">("loading");
  const [notice, setNotice] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>(() => initialMessagesForScenario("equipment-supply"));
  const [draft, setDraft] = useState("");
  const [isReplying, setIsReplying] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isFinishing, setIsFinishing] = useState(false);
  const [sent, setSent] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [attemptNumber, setAttemptNumber] = useState(1);
  const [comparison, setComparison] = useState<AttemptComparison | null>(null);
  const [historicalComparison, setHistoricalComparison] = useState<HistoricalAttemptComparison | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [sessionMode, setSessionMode] = useState<"api" | "demo">("demo");
  const [sessionNotice, setSessionNotice] = useState("");
  const [voiceDraft, setVoiceDraft] = useState<VoiceDraft | null>(null);
  const [voiceRecordings, setVoiceRecordings] = useState<VoiceRecording[]>([]);
  const [voiceNotice, setVoiceNotice] = useState("");
  const [failedMessage, setFailedMessage] = useState<string | null>(null);
  const [simulation, setSimulation] = useState<SimulationSnapshot | null>(null);
  const [isTerminal, setIsTerminal] = useState(false);
  const [report, setReport] = useState<ReportData>(demoReport);
  const [peerAssignment, setPeerAssignment] = useState<PeerReviewAssignment | null>(null);
  const [peerResult, setPeerResult] = useState<PeerReviewResult | null>(null);
  const [peerStatus, setPeerStatus] = useState<"loading" | "ready" | "submitting" | "error">("loading");
  const [peerNotice, setPeerNotice] = useState("");
  const [resumeCandidate, setResumeCandidate] = useState<StoredSessionPointer | null>(null);
  const [resumeStatus, setResumeStatus] = useState<"idle" | "loading" | "error">("idle");
  const [resumeNotice, setResumeNotice] = useState("");
  const [account, setAccount] = useState<AccountProfile | null>(null);
  const [accountChecked, setAccountChecked] = useState(false);
  const [learningDashboard, setLearningDashboard] = useState<LearningDashboard | null>(null);
  const [learningStatus, setLearningStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [guestPractice, setGuestPractice] = useState<GuestPractice[]>([]);
  const returnStep = useRef<Step>("choose");

  useEffect(() => {
    let active = true;
    getScenarios().then((result) => {
      if (!active) return;
      setScenarios(result.scenarios);
      setSelectedId(result.scenarios[0]?.id ?? "");
      setResumeCandidate(readStoredSession());
      setStatus(result.source === "api" ? "ready" : result.error ? "fallback" : "ready");
      setNotice(result.error ? "Сервер недоступен — включён локальный демонстрационный режим." : "");
    }).catch(() => {
      if (!active) return;
      setStatus("error");
      setNotice("Не удалось подготовить сценарии. Попробуйте ещё раз.");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    getCurrentAccount().then((value) => { if (active) setAccount(value); }).catch(() => { if (active) setAccount(null); }).finally(() => { if (active) setAccountChecked(true); });
    try { setGuestPractice(parseGuestPractice(JSON.parse(window.localStorage.getItem(guestPracticeKey) || "[]"))); } catch { setGuestPractice([]); }
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    getScenarioCatalog().then((result) => {
      if (!active) return;
      if (result.scenarios.length) { setCatalogScenarios(result.scenarios); setCatalogStatus("ready"); }
    }).catch(() => { /* The library can be retried when opened. */ });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!account) { setLearningDashboard(null); setLearningStatus("idle"); return; }
    if (step !== "choose") return;
    let active = true;
    setLearningStatus("loading");
    getLearningDashboard().then((result) => {
      if (!active) return;
      setLearningDashboard(result.dashboard);
      setLearningStatus(result.dashboard ? "ready" : "error");
    }).catch(() => { if (active) { setLearningDashboard(null); setLearningStatus("error"); } });
    return () => { active = false; };
  }, [account, step]);

  useEffect(() => {
    if (!account || !resumeCandidate) return;
    let active = true;
    getAccountHistory().then((result) => {
      if (!active || !result.history) return;
      const ownsStoredSession = result.history.negotiations.some((item) => item.sessionId === resumeCandidate.sessionId);
      if (!ownsStoredSession) {
        storeActiveSession(null);
        setResumeCandidate(null);
        setSessionId(null);
      }
    });
    return () => { active = false; };
  }, [account, resumeCandidate]);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(conversationFormatKey) === "text") setConversationFormat("text");
    } catch {
      // The preferred format is optional; storage restrictions must not block training.
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const heading = document.querySelector<HTMLElement>("#main-content h1");
      if (heading) {
        heading.tabIndex = -1;
        heading.focus({ preventScroll: true });
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [step]);

  const selected = useMemo(
    () => scenarios.find((scenario) => scenario.id === selectedId) ?? (randomScenario?.id === selectedId ? randomScenario : undefined),
    [scenarios, selectedId, randomScenario],
  );

  function chooseConversationFormat(value: ConversationFormat) {
    setConversationFormat(value);
    try { window.localStorage.setItem(conversationFormatKey, value); } catch { /* optional preference */ }
  }

  function dismissResume() {
    storeActiveSession(null);
    setResumeCandidate(null);
    setResumeNotice("");
    setResumeStatus("idle");
  }

  async function restoreSession(candidate: StoredSessionPointer | null = resumeCandidate) {
    if (!candidate || resumeStatus === "loading") return;
    setResumeStatus("loading");
    setResumeNotice("");
    const result = await getSession(candidate.sessionId);
    if (!result.session) {
      setResumeStatus("error");
      setResumeNotice(`${result.error || "Сессия недоступна"}. Начните новую тренировку.`);
      storeActiveSession(null);
      return;
    }
    const restored = result.session;
    let restoredScenario = scenarios.find((scenario) => scenario.id === restored.scenarioId) ?? null;
    if (!restoredScenario) {
      const scenarioResult = await getScenario(restored.scenarioId);
      restoredScenario = scenarioResult.scenario;
      if (restoredScenario?.id.startsWith("random-")) setRandomScenario(restoredScenario);
      if (restoredScenario) setScenarios((current) => [...current.filter((item) => item.id !== restoredScenario?.id), restoredScenario as Scenario]);
    }
    if (!restoredScenario) {
      setResumeStatus("error");
      setResumeNotice("Сценарий сохранённой сессии больше не доступен.");
      storeActiveSession(null);
      return;
    }
    setSelectedId(restored.scenarioId);
    if (candidate.format === "call" || candidate.format === "text") chooseConversationFormat(candidate.format);
    if (candidate.entryMode === "ready" || candidate.entryMode === "custom" || candidate.entryMode === "random") setEntryMode(candidate.entryMode);
    else setEntryMode(restoredScenario.source === "custom" ? "custom" : restoredScenario.id.startsWith("random-") ? "random" : "ready");
    setConfiguration(restored.configuration);
    setSimulation(restored.simulation);
    setSessionId(restored.sessionId);
    setAttemptNumber(restored.attemptNumber);
    setMessages([...initialMessagesForScenario(restored.scenarioId, restoredScenario.negotiationType), ...restored.messages]);
    const voiceResult = await getVoiceRecordings(restored.sessionId);
    setVoiceRecordings(voiceResult.recordings);
    setVoiceNotice(voiceResult.error || "");
    setSessionMode("api");
    const terminal = restored.status !== "active";
    setIsTerminal(terminal);
    setSent(restored.messages.length > 0);
    setFailedMessage(null);
    setSessionNotice(terminal ? "Завершённая сессия и её разбор загружены из профиля." : "Сессия восстановлена с сервера. Можно продолжать с последней реплики.");
    setResumeStatus("idle");
    if (terminal) {
      const reportResult = await completeAndGetReport(restored.sessionId);
      setReport(reportResult.report);
      const comparisonResult = restored.attemptNumber > 1 ? await getAttemptComparison(restored.sessionId) : { comparison: null, historical: null };
      setComparison(comparisonResult.comparison);
      setHistoricalComparison(comparisonResult.historical ?? null);
      storeActiveSession(null);
      setResumeCandidate(null);
      setStep("report");
    } else {
      setStep("chat");
    }
  }

  async function drawRandomScenario() {
    if (randomStatus === "loading") return;
    setEntryMode("random");
    const previousId = randomScenario?.id;
    setStep("random");
    setRandomStatus("loading");
    setRandomNotice("");
    const result = await getRandomScenario(previousId);
    if (!result.scenario) {
      setRandomStatus("error");
      setRandomNotice(result.error || "Не удалось получить случайный кейс.");
      return;
    }
    setRandomScenario(result.scenario);
    setSelectedId(result.scenario.id);
    setConfiguration(defaultConfiguration(result.scenario));
    setRandomStatus("ready");
  }

  async function openScenarioLibrary(destination: "library" | "builder" = "library") {
    setStep(destination);
    if (catalogScenarios.length) return;
    setCatalogStatus("loading");
    setCatalogNotice("");
    const result = await getScenarioCatalog();
    if (!result.scenarios.length) {
      setCatalogStatus("error");
      setCatalogNotice(result.error || "Не удалось загрузить библиотеку кейсов.");
      return;
    }
    setCatalogScenarios(result.scenarios);
    setCatalogStatus("ready");
  }

  function selectLibraryScenario(scenario: Scenario) {
    setEntryMode("ready");
    setBriefOrigin("library");
    setScenarios((current) => current.some((item) => item.id === scenario.id) ? current : [...current, scenario]);
    setSelectedId(scenario.id);
    setConfiguration(defaultConfiguration(scenario));
    setStep("brief");
  }

  function acceptBuiltScenario(draft: ScenarioDraft) {
    setEntryMode("custom");
    setBriefOrigin("builder");
    const scenario = draft.scenario;
    setScenarios((current) => [...current.filter((item) => item.id !== scenario.id), scenario]);
    setSelectedId(scenario.id);
    setConfiguration(defaultConfiguration(scenario));
    setStep("brief");
  }

  function leaveRandomChallenge() {
    const first = scenarios[0];
    setStep("choose");
    setEntryMode("random");
    setSelectedId(first?.id ?? "");
    setConfiguration(first ? defaultConfiguration(first) : null);
    setRandomStatus("idle");
    setRandomNotice("");
  }

  function retryLoad() {
    setStatus("loading");
    setNotice("");
    getScenarios().then((result) => {
      setScenarios(result.scenarios);
      setSelectedId(result.scenarios[0]?.id ?? "");
      setStatus(result.source === "api" ? "ready" : "fallback");
      setNotice(result.error ? "Сервер недоступен — включён локальный демонстрационный режим." : "");
    }).catch(() => { setStatus("error"); setNotice("Не удалось подготовить сценарии. Попробуйте ещё раз."); });
  }

  async function startSession() {
    if (!selected || isStarting) return;
    setIsStarting(true);
    const currentConfiguration = configuration ?? defaultConfiguration(selected);
    setMessages(initialMessagesForScenario(selected.id, selected.negotiationType));
    setDraft("");
    setSent(false);
    setSessionNotice("");
    setVoiceDraft(null);
    setVoiceRecordings([]);
    setVoiceNotice("");
    setFailedMessage(null);
    setIsTerminal(false);
    setComparison(null);
    setHistoricalComparison(null);
    setAttemptNumber(1);
    const result = await createSession(selected.id, currentConfiguration);
    setSessionId(result.sessionId);
    setAttemptNumber(result.attemptNumber ?? 1);
    setSessionMode(result.source);
    setSimulation(result.simulation ?? null);
    if (result.sessionId) {
      const pointer = { sessionId: result.sessionId, scenarioId: selected.id, topic: selected.title, attemptNumber: result.attemptNumber ?? 1, format: conversationFormat, entryMode };
      storeActiveSession(pointer);
      setResumeCandidate(pointer);
      setStep(entryMode === "custom" ? "prebrief" : "chat");
    } else {
      setStep("chat");
    }
    if (result.error) setSessionNotice("API недоступен во время старта — продолжена локальная демо-сессия.");
    setIsStarting(false);
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || isReplying || isTerminal) return;
    await submitMessage(text, true);
  }

  async function submitMessage(text: string, appendUser: boolean, source: "manual" | "live" = "manual"): Promise<MessageResult | null> {
    if (isReplying || isTerminal) return null;
    const optimisticId = appendUser ? createMessageId() : null;
    if (optimisticId) setMessages((current) => [...current, { id: optimisticId, author: "user", text, timestamp: "сейчас" }]);
    setDraft("");
    setFailedMessage(null);
    setIsReplying(true);
    const result = await sendSessionMessage(sessionId, text);
    if (optimisticId && result.participantMessageId) {
      setMessages((current) => current.map((item) => item.id === optimisticId ? { ...item, id: result.participantMessageId as string } : item));
    }
    const reply = result.reply;
    if (result.replies?.length) setMessages((current) => [...current, ...result.replies!]);
    else if (reply) setMessages((current) => [...current, { id: createMessageId(), author: "opponent", text: reply, timestamp: "сейчас", speakerLabel: configuration?.opponentRole }]);
    if (result.simulation) setSimulation(result.simulation);
    setSessionMode(result.source);
    if (result.error) {
      setFailedMessage(text);
      setSessionNotice(`Не удалось получить ответ оппонента: ${result.error}`);
    } else if (result.generation.fallback) {
      setSessionNotice("Gemini временно недоступен — ответ сформирован резервным движком.");
    } else {
      setSessionNotice("");
    }
    if (result.sessionStatus && result.sessionStatus !== "active") {
      setIsTerminal(true);
      setSessionNotice("Переговоры завершены. Новые сообщения недоступны — можно перейти к разбору.");
    }
    setIsReplying(false);
    if (reply) setSent(true);
    if (source === "manual" && sessionId && result.participantMessageId && voiceDraft) {
      const pending = voiceDraft;
      setVoiceDraft(null);
      if (pending.retentionPolicy === "do_not_store") {
        setVoiceNotice("Реплика отправлена. Аудио удалено локально и не передавалось на сервер.");
      } else {
        void uploadVoiceRecording(sessionId, result.participantMessageId, text, pending).then((saved) => {
          if (saved.recording) {
            setVoiceRecordings((current) => [...current.filter((item) => item.messageId !== saved.recording?.messageId), saved.recording as VoiceRecording]);
            setVoiceNotice("Аудио связано с репликой и сохранено на выбранный срок.");
          } else if (saved.error) {
            setVoiceNotice(`Реплика отправлена, но аудио не сохранилось: ${saved.error}`);
          }
        });
      }
    }
    return result;
  }

  async function removeVoiceRecording(recordingId: string) {
    if (!sessionId) return;
    const result = await deleteVoiceRecording(sessionId, recordingId);
    if (!result.ok) {
      setVoiceNotice(result.error || "Не удалось удалить аудио.");
      return;
    }
    setVoiceRecordings((current) => current.filter((item) => item.id !== recordingId));
    setVoiceNotice("Аудиозапись удалена без удаления реплики.");
  }

  async function finishSession() {
    if (isReplying || isFinishing) return;
    setIsFinishing(true);
    const result = await completeAndGetReport(sessionId);
    setReport(result.report);
    setSessionMode(result.source);
    if (!account && result.source === "api" && sessionId && selected && messages.some((message) => message.author === "user")) {
      const updated = addGuestPractice(guestPractice, { sessionId, scenarioId: selected.id, score: result.report.score, completedAt: new Date().toISOString() });
      setGuestPractice(updated);
      try { window.localStorage.setItem(guestPracticeKey, JSON.stringify(updated)); } catch { /* Storage may be unavailable. */ }
    }
    const comparisonResult = result.source === "api" && attemptNumber > 1
      ? await getAttemptComparison(sessionId)
      : { comparison: null, historical: null };
    setComparison(comparisonResult.comparison);
    setHistoricalComparison(comparisonResult.historical ?? null);
    if (result.error) setSessionNotice("Отчёт API недоступен — показан локальный демонстрационный отчёт.");
    else if (comparisonResult.error) setSessionNotice("Отчёт готов, но сравнение попыток временно недоступно.");
    setIsFinishing(false);
    if (result.source === "api") {
      storeActiveSession(null);
      setResumeCandidate(null);
    }
    setStep("report");
  }

  async function startRetry() {
    if (!selected || isRetrying) return;
    setIsRetrying(true);
    setSessionNotice("");
    const result = await retrySession(sessionId);
    if (!result.sessionId) {
      setSessionNotice(`Не удалось начать повторную попытку: ${result.error || "неизвестная ошибка"}.`);
      setIsRetrying(false);
      return;
    }
    setMessages(initialMessagesForScenario(selected.id, selected.negotiationType));
    setDraft("");
    setSent(false);
    setFailedMessage(null);
    setVoiceDraft(null);
    setVoiceRecordings([]);
    setVoiceNotice("");
    setIsTerminal(false);
    setComparison(null);
    setHistoricalComparison(null);
    setSessionId(result.sessionId);
    setAttemptNumber(result.attemptNumber ?? attemptNumber + 1);
    setSessionMode(result.source);
    setSimulation(result.simulation ?? null);
    const pointer = { sessionId: result.sessionId, scenarioId: selected.id, topic: selected.title, attemptNumber: result.attemptNumber ?? attemptNumber + 1, format: conversationFormat, entryMode };
    storeActiveSession(pointer);
    setResumeCandidate(pointer);
    setIsRetrying(false);
    setStep(entryMode === "custom" ? "prebrief" : "chat");
  }

  async function openPeerReview() {
    setStep("peer");
    setPeerAssignment(null);
    setPeerResult(null);
    setPeerStatus("loading");
    setPeerNotice("");
    const response = await getNextPeerReview(sessionId);
    if (!response.assignment) {
      setPeerStatus("error");
      setPeerNotice(response.error || "Не удалось получить диалог для проверки.");
      return;
    }
    setPeerAssignment(response.assignment);
    setPeerStatus("ready");
  }

  async function handlePeerSubmit(items: PeerReviewDraftItem[], overallComment: string) {
    if (!peerAssignment || peerStatus === "submitting") return;
    setPeerStatus("submitting");
    setPeerNotice("");
    const response = await submitPeerReview(peerAssignment.assignmentId, items, overallComment);
    if (!response.result) {
      setPeerStatus("ready");
      setPeerNotice(response.error || "Не удалось отправить рецензию.");
      return;
    }
    setPeerResult(response.result);
    setPeerStatus("ready");
    setStep("peer_result");
  }

  function openAuth() {
    returnStep.current = step === "auth" || step === "profile" ? "choose" : step;
    setStep("auth");
  }

  function openProfile() {
    returnStep.current = step === "auth" || step === "profile" ? "choose" : step;
    setStep("profile");
  }

  async function openHistorySession(item: AccountHistoryItem) {
    const pointer = { sessionId: item.sessionId, scenarioId: item.scenarioId, topic: item.topic, attemptNumber: item.attemptNumber };
    setResumeCandidate(pointer);
    await restoreSession(pointer);
  }

  function startRecommendedScenario(scenarioId: string) {
    const scenario = [...scenarios, ...catalogScenarios].find((item) => item.id === scenarioId);
    if (!scenario) {
      setStep("choose");
      return;
    }
    setScenarios((current) => current.some((item) => item.id === scenario.id) ? current : [...current, scenario]);
    setSelectedId(scenario.id);
    setEntryMode("ready");
    setBriefOrigin("choose");
    setConfiguration(defaultConfiguration(scenario));
    setStep("brief");
  }

  async function beginMotivationChallenge(kind: "daily" | "weekly", scenarioId: string, topic: string): Promise<string | null> {
    const result = await startMotivationChallenge(kind);
    if (!result.sessionId) return result.error || "Не удалось начать челлендж.";
    const pointer: StoredSessionPointer = { sessionId: result.sessionId, scenarioId: result.scenarioId ?? scenarioId, topic: result.topic ?? topic, attemptNumber: result.attemptNumber ?? 1, format: conversationFormat, entryMode: "ready" };
    storeActiveSession(pointer);
    setResumeStatus("idle");
    await restoreSession(pointer);
    return null;
  }

  async function acceptAuthenticatedAccount(value: AccountProfile, destination: Step) {
    setAccount(value);
    const result = await getAccountHistory();
    if (result.history && resumeCandidate && !result.history.negotiations.some((item) => item.sessionId === resumeCandidate.sessionId)) {
      storeActiveSession(null);
      setResumeCandidate(null);
      setSessionId(null);
    }
    setStep(destination);
  }

  const accountNavigation = { account, openAuth, openProfile };
  const framed = (content: ReactNode) => <AccountNavigationContext.Provider value={accountNavigation}>{content}</AccountNavigationContext.Provider>;
  const topicAdvice = buildTopicAdvice([...scenarios, ...catalogScenarios], learningDashboard, guestPractice, Boolean(account));

  if (step === "auth") return framed(<AuthScreen claimSessionId={sessionId} onBack={() => setStep(returnStep.current)} onAuthenticated={(value) => { void acceptAuthenticatedAccount(value, returnStep.current); }} />);
  if (step === "profile" && account) return framed(<ProfileScreen account={account} onBack={() => setStep(returnStep.current)} onOpenSession={openHistorySession} onStartRecommended={startRecommendedScenario} onStartChallenge={beginMotivationChallenge} onLoggedOut={() => { setAccount(null); storeActiveSession(null); setResumeCandidate(null); setSessionId(null); setStep("choose"); }} onDeleted={() => { setAccount(null); storeActiveSession(null); setResumeCandidate(null); setSessionId(null); setStep("choose"); }} />);
  if (step === "profile" && !account) return framed(<AuthScreen claimSessionId={sessionId} onBack={() => setStep("choose")} onAuthenticated={(value) => { void acceptAuthenticatedAccount(value, "profile"); }} />);
  if (step === "library") return framed(<ScenarioLibraryScreen scenarios={catalogScenarios} status={catalogStatus} notice={catalogNotice} onBack={() => setStep("choose")} onRetry={() => { setCatalogScenarios([]); void openScenarioLibrary("library"); }} onSelect={selectLibraryScenario} onBuild={() => void openScenarioLibrary("builder")} />);
  if (step === "builder") return framed(<ScenarioBuilderScreen account={account} templates={catalogScenarios.length ? catalogScenarios : scenarios} onBack={() => setStep("choose")} onLogin={openAuth} onCreated={acceptBuiltScenario} />);
  if (step === "configure" && selected) return framed(<ConfigureScreen scenario={selected} initial={configuration ?? defaultConfiguration(selected)} onBack={() => setStep(catalogScenarios.some((item) => item.id === selected.id) && !scenarios.slice(0, 2).some((item) => item.id === selected.id) ? "library" : "choose")} onContinue={(value) => { setConfiguration(value); setBriefOrigin("configure"); setStep("brief"); }} />);
  if (step === "random") return framed(<RandomRevealScreen status={randomStatus} scenario={randomScenario} notice={randomNotice} onBack={leaveRandomChallenge} onReroll={drawRandomScenario} onAccept={() => { setBriefOrigin("random"); setStep("brief"); }} />);
  if (step === "brief" && selected) return framed(<Briefing scenario={selected} configuration={configuration ?? defaultConfiguration(selected)} format={conversationFormat} isCustom={entryMode === "custom"} isStarting={isStarting} backLabel={{ choose: "← К выбору тренировки", configure: "← К настройке", library: "← К библиотеке", builder: "← К конструктору", random: "← К выданному кейсу" }[briefOrigin]} onBack={() => setStep(briefOrigin)} onStart={startSession} />);
  if (step === "prebrief" && selected && sessionId) return framed(<PrebriefScreen sessionId={sessionId} attemptNumber={attemptNumber} configuration={configuration ?? defaultConfiguration(selected)} onContinue={() => setStep("chat")} />);
  if (step === "chat" && selected) return framed(<Chat sessionId={sessionId} scenario={selected} configuration={configuration ?? defaultConfiguration(selected)} preferredFormat={conversationFormat} attemptNumber={attemptNumber} messages={messages} simulation={simulation} onSimulation={setSimulation} draft={draft} isReplying={isReplying} isFinishing={isFinishing} isTerminal={isTerminal} sent={sent} notice={sessionNotice} failedMessage={failedMessage} voiceDraft={voiceDraft} voiceRecordings={voiceRecordings} voiceNotice={voiceNotice} onDraft={setDraft} onVoiceDraft={setVoiceDraft} onDeleteVoice={removeVoiceRecording} onSend={sendMessage} onAutoTurn={(text) => submitMessage(text, true, "live")} onRetryMessage={() => failedMessage && submitMessage(failedMessage, false)} onFinish={finishSession} />);
  if (step === "report" && selected) return framed(<Report sessionId={sessionId} scenario={selected} configuration={configuration ?? defaultConfiguration(selected)} report={report} attemptNumber={attemptNumber} comparison={comparison} historicalComparison={historicalComparison} mode={sessionMode} notice={sessionNotice} isRetrying={isRetrying} onCompare={() => setStep("comparison")} onPeer={openPeerReview} onRetry={startRetry} onChange={() => { storeActiveSession(null); setResumeCandidate(null); setStep("choose"); setSessionId(null); setAttemptNumber(1); setComparison(null); setHistoricalComparison(null); setConfiguration(null); setRandomScenario(null); setRandomStatus("idle"); }} />);
  if (step === "peer") return framed(<PeerReviewScreen assignment={peerAssignment} status={peerStatus} notice={peerNotice} onBack={() => setStep("report")} onRetry={openPeerReview} onSubmit={handlePeerSubmit} />);
  if (step === "peer_result" && peerResult) return framed(<PeerReviewResultScreen result={peerResult} onBack={() => setStep("report")} onNext={openPeerReview} />);
  if (step === "comparison" && comparison) return framed(<AttemptComparisonScreen comparison={comparison} onBack={() => setStep("report")} onRetry={startRetry} isRetrying={isRetrying} />);
  if (step === "comparison" && historicalComparison) return framed(<HistoricalAttemptComparisonScreen comparison={historicalComparison} onBack={() => setStep("report")} onRetry={startRetry} isRetrying={isRetrying} />);

  return framed(
    <main className="app-shell home-shell">
      <Topbar step={step} />
      <section className="home-workspace" id="main-content" aria-labelledby="home-title">
        <div className="home-hero">
          <div className="home-hero-copy"><span className="eyebrow">Арена переговоров</span><h1 id="home-title"><span>Говорите смелее.</span><br />Договаривайтесь лучше.</h1><p>Переговоры с AI-оппонентом. Голосом или текстом.</p></div>
          <HeroConversationPreview />
        </div>

        {resumeCandidate && <article className="resume-card" aria-labelledby="resume-title"><div className="resume-icon" aria-hidden="true">↻</div><div><span className="card-topline">Ваш незавершённый разговор</span><h2 id="resume-title">{resumeCandidate.topic}</h2>{resumeNotice && <p className="field-error" role="alert">{resumeNotice}</p>}</div><div className="resume-actions"><button className="button primary" type="button" onClick={() => restoreSession()} disabled={resumeStatus === "loading"}>{resumeStatus === "loading" ? "Открываем…" : "Продолжить"}</button><button className="text-button" type="button" onClick={dismissResume}>Скрыть</button></div></article>}
        {notice && <div className={`notice ${status === "error" ? "notice-error" : ""}`} role="status">{notice} {status === "error" && <button className="text-button" onClick={retryLoad}>Повторить</button>}</div>}

        <div className="home-start-panel" id="training-setup">
        <div className="home-step-heading home-format-heading"><div><h2>Как общаться?</h2></div></div>
        <div className="home-format-grid" role="group" aria-label="Формат общения"><button className={`home-format-card ${conversationFormat === "call" ? "selected" : ""}`} type="button" aria-pressed={conversationFormat === "call"} onClick={() => chooseConversationFormat("call")}><span className="home-format-icon" aria-hidden="true">◉</span><span><strong>Звонок</strong></span></button><button className={`home-format-card ${conversationFormat === "text" ? "selected" : ""}`} type="button" aria-pressed={conversationFormat === "text"} onClick={() => chooseConversationFormat("text")}><span className="home-format-icon" aria-hidden="true">▤</span><span><strong>Текст</strong></span></button></div>

        <div className="home-step-heading"><div><h2>Что тренировать?</h2></div></div>
        <div className="home-entry-grid" role="group" aria-label="Вид тренировки">
          <button className={`home-entry-card ${entryMode === "ready" ? "selected" : ""}`} type="button" aria-pressed={entryMode === "ready"} onClick={() => setEntryMode("ready")}><span className="home-entry-symbol" aria-hidden="true">↗</span><strong>Готовый кейс</strong><i aria-hidden="true">→</i></button>
          <button className={`home-entry-card ${entryMode === "custom" ? "selected" : ""}`} type="button" aria-pressed={entryMode === "custom"} onClick={() => setEntryMode("custom")}><span className="home-entry-symbol" aria-hidden="true">◎</span><strong>Свой кейс</strong><i aria-hidden="true">→</i></button>
          <button className={`home-entry-card ${entryMode === "random" ? "selected" : ""}`} type="button" aria-pressed={entryMode === "random"} onClick={() => setEntryMode("random")}><span className="home-entry-symbol" aria-hidden="true">✳</span><strong>Случайный</strong><i aria-hidden="true">→</i></button>
        </div>
        {entryMode !== "random" && status !== "loading" && status !== "error" && scenarios.length > 0 && <label className="home-case-picker" htmlFor="home-case-select"><span>Тема</span><select id="home-case-select" value={selectedId} onChange={(event) => { const scenario = scenarios.find((item) => item.id === event.target.value); if (scenario) { setSelectedId(scenario.id); setConfiguration(defaultConfiguration(scenario)); } }}>{scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.title}</option>)}</select></label>}
        {status === "loading" && <p className="home-loading" role="status">Загружаем сценарии…</p>}

        <div className="home-footer"><button className="button primary home-start" type="button" disabled={entryMode !== "random" && (!selected || status === "loading" || status === "error")} onClick={() => { if (entryMode === "random") { void drawRandomScenario(); return; } if (!selected) return; setConfiguration(entryMode === "ready" ? defaultConfiguration(selected) : configuration ?? defaultConfiguration(selected)); if (entryMode === "ready") setBriefOrigin("choose"); setStep(entryMode === "custom" ? "configure" : "brief"); }}>{entryMode === "random" ? "Получить кейс" : entryMode === "custom" ? "Настроить" : "Начать"}<span aria-hidden="true">→</span></button></div>
        </div>
        <TrainingFlow />
        {accountChecked && topicAdvice.items.length > 0 && <section className="home-advice" aria-labelledby="home-advice-title">
          <div className="home-advice-heading"><div><span className="eyebrow">{topicAdvice.kind === "starter" ? "Стартовый кейс" : "Подобрано для вас"}</span><h2 id="home-advice-title">Попробуйте сейчас</h2>{account && learningStatus === "error" && <p>Пока показываем стартовую тему.</p>}</div></div>
          <div className="home-advice-grid">{topicAdvice.items.slice(0, 1).map((item) => <article className="home-advice-card" key={item.scenario.id}><span className="home-advice-focus">Фокус: {item.focus}</span><h3>{item.scenario.title}</h3><p className="home-advice-reason">{item.reason}</p><button type="button" onClick={() => startRecommendedScenario(item.scenario.id)}>Выбрать кейс <span aria-hidden="true">→</span></button></article>)}</div>
        </section>}
        <div className="home-secondary-links"><button type="button" onClick={() => void openScenarioLibrary("library")}>Все кейсы <span aria-hidden="true">↗</span></button><button type="button" onClick={() => void openScenarioLibrary("builder")}>Создать кейс <span aria-hidden="true">↗</span></button></div>
      </section>
    </main>
  );
}

function ScenarioLibraryScreen({ scenarios, status, notice, onBack, onRetry, onSelect, onBuild }: { scenarios: Scenario[]; status: "idle" | "loading" | "ready" | "error"; notice: string; onBack: () => void; onRetry: () => void; onSelect: (scenario: Scenario) => void; onBuild: () => void }) {
  const [query, setQuery] = useState("");
  const [industry, setIndustry] = useState("all");
  const [theme, setTheme] = useState("all");
  const [difficulty, setDifficulty] = useState("all");
  const [method, setMethod] = useState("all");
  const [maxMinutes, setMaxMinutes] = useState(120);
  const industries = useMemo(() => [...new Set(scenarios.map((item) => item.industry || "Общее"))].sort(), [scenarios]);
  const themes = useMemo(() => [...new Set(scenarios.map((item) => item.theme || "Деловые переговоры"))].sort(), [scenarios]);
  const methods = useMemo(() => [...new Set(scenarios.flatMap((item) => item.methods || []))].sort(), [scenarios]);
  const methodLabel: Record<string, string> = { principled_negotiation: "Гарвардский метод", seven_elements: "7 элементов", active_listening: "Активное слушание", integrative: "Интегративные переговоры", distributive: "Дистрибутивные переговоры", meso: "MESO", spin: "SPIN", nvc: "Ненасильственное общение", anchoring: "Якорение", contingent_agreement: "Условные соглашения", behavioral_change_stairway: "Лестница изменения поведения" };
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ru-RU");
    return scenarios.filter((item) => {
      const text = [item.title, item.description, item.role, item.opponent, ...(item.roleTags || [])].join(" ").toLocaleLowerCase("ru-RU");
      return (!needle || text.includes(needle))
        && (industry === "all" || item.industry === industry)
        && (theme === "all" || item.theme === theme)
        && (difficulty === "all" || item.difficulty === difficulty)
        && (method === "all" || item.methods?.includes(method))
        && Number.parseInt(item.duration, 10) <= maxMinutes;
    });
  }, [scenarios, query, industry, theme, difficulty, method, maxMinutes]);
  const reset = () => { setQuery(""); setIndustry("all"); setTheme("all"); setDifficulty("all"); setMethod("all"); setMaxMinutes(120); };

  return <main className="app-shell"><Topbar step="library" /><section className="workspace library-workspace" id="main-content" aria-labelledby="library-title">
    <button className="back-button" type="button" onClick={onBack}>← К быстрому старту</button>
    <header className="library-hero"><div><div className="eyebrow">Выберите свою задачу</div><h1 id="library-title">Кейсы для практики</h1></div><button className="button secondary" type="button" onClick={onBuild}>Создать кейс <span aria-hidden="true">◇</span></button></header>
    <label className="library-search library-search-main"><span className="sr-only">Поиск по теме или роли</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти кейс" /></label>
    <details className="library-filter-disclosure"><summary>Фильтры</summary><div className="library-filters" aria-label="Фильтры библиотеки">
      <label><span>Направление</span><select value={theme} onChange={(event) => setTheme(event.target.value)}><option value="all">Все направления</option>{themes.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label><span>Отрасль</span><select value={industry} onChange={(event) => setIndustry(event.target.value)}><option value="all">Все отрасли</option>{industries.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label><span>Сложность</span><select value={difficulty} onChange={(event) => setDifficulty(event.target.value)}><option value="all">Любая</option><option value="easy">Поддерживающая</option><option value="medium">Сбалансированная</option><option value="hard">Требовательная</option></select></label>
      <label><span>Методика</span><select value={method} onChange={(event) => setMethod(event.target.value)}><option value="all">Любая методика</option>{methods.map((item) => <option value={item} key={item}>{methodLabel[item] || item}</option>)}</select></label>
      <label><span>Длительность</span><select value={maxMinutes} onChange={(event) => setMaxMinutes(Number(event.target.value))}><option value={15}>До 15 минут</option><option value={30}>До 30 минут</option><option value={60}>До 60 минут</option><option value={120}>Любая</option></select></label>
    </div></details>
    {status === "loading" || status === "idle" ? <div className="library-grid" aria-label="Загрузка библиотеки">{[1,2,3,4,5,6].map((item) => <div className="skeleton library-skeleton" key={item} />)}</div> : status === "error" ? <div className="empty-state"><h2>Библиотека не загрузилась</h2><p role="alert">{notice}</p><button className="button primary" onClick={onRetry}>Повторить</button></div> : <>
      <div className="library-result-bar"><span>Найдено <strong>{filtered.length}</strong> из {scenarios.length}</span><button className="text-button" type="button" onClick={reset}>Сбросить фильтры</button></div>
      {filtered.length ? <div className="library-grid">{filtered.map((scenario) => <article className="library-card" key={scenario.id}><div className="library-card-top"><span>{scenario.theme}</span><small>{scenario.duration}</small></div><h2>{scenario.title}</h2><div className="library-tags"><span>{difficultyLabel[scenario.difficulty ?? "medium"]}</span><span>{scenario.industry}</span></div><button className="button secondary" type="button" onClick={() => onSelect(scenario)}>Выбрать <span aria-hidden="true">→</span></button></article>)}</div> : <div className="empty-state"><h2>Кейсов не найдено</h2><p>Попробуйте другие фильтры.</p><div className="action-row"><button className="button primary" onClick={reset}>Сбросить фильтры</button><button className="button secondary" onClick={onBuild}>Создать кейс</button></div></div>}
    </>}
  </section></main>;
}

function ScenarioBuilderScreen({ account, templates, onBack, onLogin, onCreated }: { account: AccountProfile | null; templates: Scenario[]; onBack: () => void; onLogin: () => void; onCreated: (draft: ScenarioDraft) => void }) {
  const first = templates.find((item) => item.source !== "custom") || templates[0];
  const [value, setValue] = useState<ScenarioDraftInput>(() => ({ templateId: first?.id || "equipment-supply", title: "", situation: "", participantRole: "", opponentRole: "", objective: "", industry: first?.industry || "Технологии", theme: first?.theme || "Закупки", difficulty: "medium", tone: "businesslike", estimatedMinutes: 15, maxTurns: 12, stakesLevel: "standard" }));
  const [drafts, setDrafts] = useState<ScenarioDraft[]>([]);
  const [saved, setSaved] = useState<ScenarioDraft | null>(null);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [suggesting, setSuggesting] = useState(false);

  useEffect(() => {
    if (!account) return;
    getScenarioDrafts().then((result) => { setDrafts(result.drafts); if (result.error) setNotice(result.error); });
  }, [account]);
  useEffect(() => {
    if (!value.templateId && first) setValue((current) => ({ ...current, templateId: first.id, industry: first.industry || current.industry, theme: first.theme || current.theme }));
  }, [first, value.templateId]);

  if (!account) return <main className="app-shell"><Topbar step="builder" /><section className="workspace builder-workspace" id="main-content" aria-labelledby="builder-title"><button className="back-button" type="button" onClick={onBack}>← К сценариям</button><div className="builder-auth"><span aria-hidden="true">◇</span><div className="eyebrow">Версионируемый черновик</div><h1 id="builder-title">Войдите, чтобы создать свой кейс</h1><p>Аккаунт нужен, чтобы версии кейса сохранялись на сервере и оставались доступны после перезапуска приложения.</p><button className="button primary" type="button" onClick={onLogin}>Войти или зарегистрироваться</button></div></section></main>;

  const set = <K extends keyof ScenarioDraftInput>(key: K, next: ScenarioDraftInput[K]) => setValue((current) => ({ ...current, [key]: next }));
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    setSaving(true); setNotice("");
    const result = await saveScenarioDraft(value);
    setSaving(false);
    if (!result.draft) { setNotice(result.error || "Не удалось проверить черновик."); return; }
    setSaved(result.draft);
    setDrafts((current) => [result.draft as ScenarioDraft, ...current]);
    setValue((current) => ({ ...current, seriesId: result.draft?.seriesId }));
    setNotice(`Версия ${result.draft.version} сохранена: границы сделки согласованы.`);
  };
  const improve = async () => {
    if (suggesting || value.title.length < 3 || value.situation.length < 10 || value.objective.length < 5) { setNotice("Сначала заполните тему, ситуацию и цель."); return; }
    setSuggesting(true); setNotice("");
    const result = await suggestScenarioText(value);
    setSuggesting(false);
    if (!result.suggestion) { setNotice(result.error || "Помощник недоступен."); return; }
    setValue((current) => ({ ...current, title: result.suggestion!.title, situation: result.suggestion!.situation, objective: result.suggestion!.objective }));
    setNotice(result.suggestion.fallback ? "Текст проверен локально; Gemini временно недоступен." : "Gemini улучшил только публичную формулировку. Скрытая экономика не передавалась модели.");
  };

  return <main className="app-shell"><Topbar step="builder" /><section className="workspace builder-workspace" id="main-content" aria-labelledby="builder-title"><button className="back-button" type="button" onClick={onBack}>← К сценариям</button><header className="builder-hero"><div><div className="eyebrow">Безопасный конструктор · {value.seriesId ? "новая версия" : "новый черновик"}</div><h1 id="builder-title">Соберите свой переговорный кейс</h1><p className="lead">Вы задаёте только публичную ситуацию. ZOPA, BATNA, reservation point и скрытые интересы берутся из валидированного шаблона и не раскрываются.</p></div><div className="builder-shield"><span aria-hidden="true">✓</span><strong>Экономика защищена</strong><small>LLM не назначает границы сделки</small></div></header>
    {notice && <div className={`notice ${notice.includes("Не удалось") ? "notice-error" : ""}`} role="status">{notice}</div>}
    <div className="builder-layout"><form className="builder-form" onSubmit={submit}>
      <section><div className="configure-section-heading"><span>01</span><div><h2>Экономический шаблон</h2><p>Шаблон определяет скрытую механику. Пользователь не редактирует границы напрямую.</p></div></div><label>Основа кейса<select value={value.templateId} onChange={(event) => set("templateId", event.target.value)}>{templates.filter((item) => item.source !== "custom").map((item) => <option value={item.id} key={item.id}>{item.title} · {item.theme}</option>)}</select></label><div className="builder-triple"><label>Направление<input required minLength={2} maxLength={80} value={value.theme} onChange={(event) => set("theme", event.target.value)} /></label><label>Отрасль<input required minLength={2} maxLength={80} value={value.industry} onChange={(event) => set("industry", event.target.value)} /></label><label>Масштаб<select value={value.stakesLevel} onChange={(event) => set("stakesLevel", event.target.value as ScenarioDraftInput["stakesLevel"])}><option value="low">Ниже шаблона</option><option value="standard">Стандартный</option><option value="high">Выше шаблона</option></select></label></div></section>
      <section><div className="configure-section-heading"><span>02</span><div><h2>Публичный контекст</h2><p>Эти данные увидят участник и AI-оппонент.</p></div></div><label>Название<input required minLength={5} maxLength={120} value={value.title} onChange={(event) => set("title", event.target.value)} placeholder="Например, продление контракта на логистику" /></label><label>Ситуация<textarea required minLength={30} maxLength={1200} rows={5} value={value.situation} onChange={(event) => set("situation", event.target.value)} placeholder="Что уже известно сторонам и что предстоит согласовать?" /></label><label>Цель участника<textarea required minLength={10} maxLength={500} rows={3} value={value.objective} onChange={(event) => set("objective", event.target.value)} placeholder="Какой измеримый результат нужно получить?" /></label><button className="text-button ai-text-button" type="button" onClick={improve} disabled={suggesting}>{suggesting ? "Улучшаем формулировку…" : "✦ Улучшить публичный текст с Gemini"}</button></section>
      <section><div className="configure-section-heading"><span>03</span><div><h2>Роли и формат</h2><p>Роли меняют только публичную подачу; скрытые условия остаются валидированными.</p></div></div><div className="builder-two"><label>Ваша роль<input required minLength={2} maxLength={100} value={value.participantRole} onChange={(event) => set("participantRole", event.target.value)} /></label><label>Роль оппонента<input required minLength={2} maxLength={100} value={value.opponentRole} onChange={(event) => set("opponentRole", event.target.value)} /></label><label>Сложность<select value={value.difficulty} onChange={(event) => set("difficulty", event.target.value as SessionConfiguration["difficulty"])}>{difficultyOptions.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label><label>Тон<select value={value.tone} onChange={(event) => set("tone", event.target.value as SessionConfiguration["tone"])}>{toneOptions.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label><label>Минут<input type="number" min={5} max={60} value={value.estimatedMinutes} onChange={(event) => set("estimatedMinutes", Number(event.target.value))} /></label><label>Ходов<input type="number" min={6} max={20} value={value.maxTurns} onChange={(event) => set("maxTurns", Number(event.target.value))} /></label></div></section>
      <div className="builder-actions"><button className="button primary" type="submit" disabled={saving}>{saving ? "Проверяем границы…" : value.seriesId ? "Сохранить новую версию" : "Проверить и сохранить"}</button>{saved && <button className="button secondary" type="button" onClick={() => onCreated(saved)}>Запустить версию {saved.version} →</button>}</div>
    </form><aside className="builder-aside"><div className="validation-preview"><span className="card-topline">Автоматическая проверка</span><h2>{saved ? "Кейс готов к тренировке" : "Что проверит система"}</h2><ul><li><span>✓</span>ZOPA пересчитана по всем вопросам</li><li><span>✓</span>BATNA обеих сторон находится в допустимой шкале</li><li><span>✓</span>Reservation point согласован с направлением предпочтений</li><li><span>✓</span>Скрытые поля отсутствуют в публичном API</li></ul>{saved && <dl><div><dt>Версия</dt><dd>{saved.version}</dd></div><div><dt>Вопросов</dt><dd>{saved.validation.checkedIssues}</dd></div><div><dt>Пересечений</dt><dd>{saved.validation.overlappingIssues}</dd></div></dl>}</div><div className="draft-history"><span className="card-topline">Мои версии</span><h2>Черновики</h2>{drafts.length ? drafts.slice(0,6).map((item) => <button type="button" key={item.id} onClick={() => onCreated(item)}><span><strong>{item.scenario.title}</strong><small>Версия {item.version} · {new Date(item.createdAt).toLocaleDateString("ru-RU")}</small></span><b>→</b></button>) : <p>После первого сохранения версии появятся здесь.</p>}</div></aside></div>
  </section></main>;
}

function RandomRevealScreen({ status, scenario, notice, onBack, onReroll, onAccept }: { status: "idle" | "loading" | "ready" | "error"; scenario: Scenario | null; notice: string; onBack: () => void; onReroll: () => void; onAccept: () => void }) {
  const loading = status === "loading";
  return <main className="app-shell"><Topbar step="random" /><section className="workspace random-reveal" id="main-content" aria-labelledby="random-title">
    <button className="back-button" type="button" onClick={onBack}>← К сценариям</button>
    {loading ? <div className="random-loading" role="status" aria-live="polite"><span className="random-orbit" aria-hidden="true">⚄</span><div className="eyebrow">Генератор вызова</div><h1 id="random-title">Выбираем ваш кейс…</h1><p>Сверяем роли, задачи и границы сделки.</p></div> : status === "error" ? <div className="empty-state"><div className="eyebrow">Случайный кейс</div><h1 id="random-title">Вызов не загрузился</h1><p role="alert">{notice}</p><button className="button primary" type="button" onClick={onReroll}>Попробовать ещё раз</button></div> : scenario ? <>
      <div className="random-reveal-heading"><div><div className="eyebrow">Случай выпал · условия зафиксированы</div><h1 id="random-title">{scenario.title}</h1><p className="lead">{scenario.context}</p></div><span className="challenge-number" aria-label="Случайный вызов">⚄</span></div>
      <div className="random-brief-grid"><article className="panel random-role-panel"><span className="card-topline">Ваша роль</span><h2>{scenario.role}</h2><p>{scenario.objective}</p><div className="random-meta"><span>{scenario.duration}</span><span>{difficultyLabel[scenario.difficulty ?? "medium"]}</span><span>{scenario.maxTurns ?? 12} ходов</span></div></article><article className="panel"><span className="card-topline">Ваш оппонент</span><h2>{scenario.opponent}</h2><p>Его границы, BATNA и скрытые интересы не показаны. Выясните их в диалоге.</p></article></div>
      <section className="random-tasks" aria-labelledby="random-tasks-title"><div className="section-heading"><div><span className="card-topline">Условия успеха</span><h2 id="random-tasks-title">Что нужно выполнить</h2></div><span className="task-count">{scenario.tasks.length} задач</span></div><ol>{scenario.tasks.map((task, index) => <li key={task.id}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{task.title}</strong><p>{task.description}</p></div></li>)}</ol></section>
      <div className="random-actions"><button className="button primary" type="button" onClick={onAccept}>Принять вызов <span aria-hidden="true">→</span></button><button className="button secondary" type="button" onClick={onReroll}>Другой случай</button><span>Повторный выбор не вернёт тот же кейс.</span></div>
    </> : null}
  </section></main>;
}

function Onboarding({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLElement>(null);
  const startButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    startButton.current?.focus();
    const handleKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const controls = dialog.current?.querySelectorAll<HTMLElement>('button,[href],[tabindex]:not([tabindex="-1"])');
      if (!controls?.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);
  return <div className="onboarding-backdrop" role="presentation"><section ref={dialog} className="onboarding-dialog" role="dialog" aria-modal="true" aria-labelledby="onboarding-title" aria-describedby="onboarding-description"><span className="card-topline">Первый вход · 3 шага</span><h1 id="onboarding-title">Тренируйтесь, ошибайтесь безопасно, пробуйте снова</h1><p id="onboarding-description">«Арена переговоров» даёт практику с AI-оппонентом и показывает не только балл, но и доказательства из диалога.</p><ol><li><span>01</span><div><strong>Выберите и настройте кейс</strong><p>Роль, цель, сложность, тон и длительность — под вашу задачу.</p></div></li><li><span>02</span><div><strong>Проведите переговоры</strong><p>Ищите интересы, предлагайте обмены и фиксируйте условия.</p></div></li><li><span>03</span><div><strong>Разберите результат</strong><p>Получите отчёт Gemini, peer-review и сравнение повторных попыток.</p></div></li></ol><div className="onboarding-actions"><button ref={startButton} className="button primary" type="button" onClick={onClose}>Выбрать сценарий <span aria-hidden="true">→</span></button><span>Esc — закрыть</span></div></section></div>;
}

function Topbar({ step }: { step: Step }) {
  const { account, openAuth, openProfile } = useContext(AccountNavigationContext);
  const titles: Record<Step, string> = { choose: "Новая тренировка", library: "Библиотека кейсов", builder: "Конструктор кейса", random: "Случайный вызов", configure: "Настройка", brief: "Брифинг", prebrief: "Подготовка", chat: "Переговоры", report: "Разбор", peer: "Взаимная проверка", peer_result: "Сверка оценок", comparison: "Прогресс", auth: "Вход", profile: "Личный кабинет" };
  return <><a className="skip-link" href="#main-content">Перейти к содержанию</a><header className="topbar"><a className="brand" href="/" aria-label="Арена переговоров, на главную"><span className="brand-mark">A</span><span>Арена переговоров</span></a><div className="topbar-actions"><div className="step-indicator" aria-label={`Текущий этап: ${titles[step]}`}>{titles[step]}</div><button className="account-trigger" type="button" aria-label={account ? `Открыть личный кабинет: ${account.displayName}` : "Войти в личный кабинет"} onClick={account ? openProfile : openAuth}>{account ? <><span className="account-avatar" aria-hidden="true">{account.displayName.slice(0, 1).toUpperCase()}</span><span>{account.displayName}</span></> : "Войти"}</button></div></header></>;
}

function RecoveryCodeCard({ code, onContinue, continueLabel }: { code: string; onContinue: () => void; continueLabel: string }) {
  const [copied, setCopied] = useState(false);
  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return <section className="recovery-card" aria-labelledby="recovery-code-title"><span className="recovery-icon" aria-hidden="true">◇</span><div className="eyebrow">Показываем один раз</div><h1 id="recovery-code-title">Сохраните резервный код</h1><p className="lead">Он восстановит доступ, если вы забудете пароль. Мы не отправляем код по почте и не сможем показать его повторно.</p><code>{code}</code><div className="recovery-actions"><button className="button secondary" type="button" onClick={copyCode}>{copied ? "Скопировано" : "Скопировать код"}</button><button className="button primary" type="button" onClick={onContinue}>{continueLabel} <span aria-hidden="true">→</span></button></div></section>;
}

function AuthScreen({ claimSessionId, onBack, onAuthenticated }: { claimSessionId: string | null; onBack: () => void; onAuthenticated: (account: AccountProfile) => void }) {
  const [mode, setMode] = useState<"login" | "register" | "recover">("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [recoveryInput, setRecoveryInput] = useState("");
  const [issuedCode, setIssuedCode] = useState("");
  const [pendingAccount, setPendingAccount] = useState<AccountProfile | null>(null);
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function switchMode(next: "login" | "register" | "recover") {
    setMode(next);
    setNotice("");
    setIssuedCode("");
    setPendingAccount(null);
    setPassword("");
    setPasswordConfirm("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if ((mode === "register" || mode === "recover") && password !== passwordConfirm) {
      setNotice("Пароли не совпадают.");
      return;
    }
    setSubmitting(true);
    setNotice("");
    if (mode === "recover") {
      const result = await recoverAccount(email.trim(), recoveryInput.trim(), password);
      setSubmitting(false);
      if (result.error || !result.recoveryCode) {
        setNotice(result.error || "Не удалось изменить пароль.");
        return;
      }
      setIssuedCode(result.recoveryCode);
      return;
    }
    const result = mode === "register"
      ? await registerAccount(email.trim(), displayName.trim(), password, claimSessionId)
      : await loginAccount(email.trim(), password, claimSessionId);
    setSubmitting(false);
    if (!result.account) {
      setNotice(result.error || "Не удалось войти.");
      return;
    }
    if (result.recoveryCode) {
      setPendingAccount(result.account);
      setIssuedCode(result.recoveryCode);
      return;
    }
    onAuthenticated(result.account);
  }

  if (issuedCode) return <main className="app-shell"><Topbar step="auth" /><section className="workspace auth-workspace" id="main-content">{mode === "register" && pendingAccount
    ? <RecoveryCodeCard code={issuedCode} onContinue={() => onAuthenticated(pendingAccount)} continueLabel="Перейти к тренировке" />
    : <RecoveryCodeCard code={issuedCode} onContinue={() => switchMode("login")} continueLabel="Войти с новым паролем" />}</section></main>;

  return <main className="app-shell"><Topbar step="auth" /><section className="workspace auth-workspace" id="main-content" aria-labelledby="auth-title"><button className="back-button" type="button" onClick={onBack}>← Вернуться</button><div className="auth-layout"><div className="auth-intro"><div className="eyebrow">Ваш прогресс — на любом устройстве</div><h1 id="auth-title">Личный кабинет переговорщика</h1><p className="lead">Сохраняйте диалоги, отчёты, повторные попытки и свою практику peer-review в защищённом профиле.</p><ul><li><span>01</span><div><strong>История не потеряется</strong><p>Продолжайте активный диалог после входа с другого устройства.</p></div></li><li><span>02</span><div><strong>Данные разделены</strong><p>Другие участники не видят ваши переговоры и отчёты.</p></div></li><li><span>03</span><div><strong>Минимум данных</strong><p>Нужны только имя для интерфейса и email для входа.</p></div></li></ul></div><form className="auth-panel" onSubmit={submit}><div className="auth-tabs" role="tablist" aria-label="Режим доступа"><button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : ""} onClick={() => switchMode("login")}>Вход</button><button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "active" : ""} onClick={() => switchMode("register")}>Регистрация</button></div><span className="card-topline">{mode === "login" ? "С возвращением" : mode === "register" ? "Новый профиль" : "Восстановление"}</span><h2>{mode === "login" ? "Войти в аккаунт" : mode === "register" ? "Создать аккаунт" : "Задать новый пароль"}</h2>{mode === "register" && <label>Имя в интерфейсе<input autoComplete="name" minLength={2} maxLength={80} required value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Например, Алексей" /></label>}<label>Email<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" /></label>{mode === "recover" && <label>Резервный код<input autoComplete="off" required value={recoveryInput} onChange={(event) => setRecoveryInput(event.target.value.toUpperCase())} placeholder="XXXX-XXXX-XXXX-XXXX" /></label>}<label>{mode === "recover" ? "Новый пароль" : "Пароль"}<input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "login" ? 1 : 10} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "login" ? "Ваш пароль" : "Не менее 10 символов, буквы и цифры"} /></label>{mode !== "login" && <label>Повторите пароль<input type="password" autoComplete="new-password" minLength={10} maxLength={128} required value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} placeholder="Повторите пароль" /></label>}{claimSessionId && mode !== "recover" && <div className="claim-note"><span aria-hidden="true">↻</span><p>Текущая тренировка будет добавлена в ваш профиль после входа.</p></div>}{notice && <div className="notice notice-error compact" role="alert">{notice}</div>}<button className="button primary auth-submit" type="submit" disabled={submitting}>{submitting ? "Проверяем…" : mode === "login" ? "Войти" : mode === "register" ? "Создать аккаунт" : "Изменить пароль"}</button>{mode === "login" && <button className="text-button auth-recover" type="button" onClick={() => switchMode("recover")}>Не помню пароль</button>}{mode === "recover" && <button className="text-button auth-recover" type="button" onClick={() => switchMode("login")}>Вернуться ко входу</button>}</form></div></section></main>;
}

function ProfileScreen({ account, onBack, onOpenSession, onStartRecommended, onStartChallenge, onLoggedOut, onDeleted }: { account: AccountProfile; onBack: () => void; onOpenSession: (item: AccountHistoryItem) => void; onStartRecommended: (scenarioId: string) => void; onStartChallenge: (kind: "daily" | "weekly", scenarioId: string, topic: string) => Promise<string | null>; onLoggedOut: () => void; onDeleted: () => void }) {
  const [history, setHistory] = useState<AccountHistory | null>(null);
  const [learning, setLearning] = useState<LearningDashboard | null>(null);
  const [notice, setNotice] = useState("");
  const [learningNotice, setLearningNotice] = useState("");
  const [motivation, setMotivation] = useState<MotivationDashboard | null>(null);
  const [motivationNotice, setMotivationNotice] = useState("");
  const [motivationLoading, setMotivationLoading] = useState(true);
  const [motivationRefreshKey, setMotivationRefreshKey] = useState(0);
  const [profileTab, setProfileTab] = useState<"overview" | "growth" | "challenges" | "history">("overview");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([getAccountHistory(), getLearningDashboard()]).then(([historyResult, learningResult]) => {
      if (!active) return;
      setHistory(historyResult.history);
      setLearning(learningResult.dashboard);
      setNotice(historyResult.error || "");
      setLearningNotice(learningResult.error || "");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setMotivationLoading(true);
    getMotivationDashboard().then((result) => {
      if (!active) return;
      setMotivation(result.dashboard);
      setMotivationNotice(result.error || "");
      setMotivationLoading(false);
    });
    return () => { active = false; };
  }, [motivationRefreshKey]);

  async function logout() {
    if (await logoutAccount()) onLoggedOut();
    else setNotice("Не удалось завершить сессию. Попробуйте ещё раз.");
  }

  async function removeAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (deleting) return;
    setDeleting(true);
    const result = await deleteAccount(deletePassword);
    setDeleting(false);
    if (result.ok) onDeleted();
    else setNotice(result.error || "Не удалось удалить аккаунт.");
  }

  const completed = history?.negotiations.filter((item) => item.status === "completed") ?? [];
  const scores = completed.flatMap((item) => item.score === null ? [] : [item.score]);
  const best = scores.length ? Math.max(...scores) : null;
  const date = (value: string) => new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));

  return <main className="app-shell"><Topbar step="profile" /><section className="workspace profile-workspace" id="main-content" aria-labelledby="profile-title">
    <button className="back-button" type="button" onClick={onBack}>← К тренировке</button>
    <header className="profile-hero"><div className="profile-avatar" aria-hidden="true">{account.displayName.slice(0, 1).toUpperCase()}</div><div><div className="eyebrow">Профиль</div><h1 id="profile-title">{account.displayName}</h1><p>{account.email}</p></div><button className="button secondary" type="button" onClick={logout}>Выйти</button></header>
    {notice && <div className="notice notice-error" role="alert">{notice}</div>}
    <nav className="profile-tabs" aria-label="Разделы профиля">{([ ["overview", "Главное"], ["growth", "Навыки"], ["challenges", "Вызовы"], ["history", "История"] ] as const).map(([value, label]) => <button key={value} type="button" className={profileTab === value ? "active" : ""} aria-current={profileTab === value ? "page" : undefined} onClick={() => setProfileTab(value)}>{label}</button>)}</nav>
    {profileTab === "overview" && <>
      <section className="profile-stats" aria-label="Статистика профиля"><article><span>Завершено</span><strong>{history ? completed.length : "—"}</strong></article><article><span>Лучший балл</span><strong>{best ?? "—"}</strong></article></section>
      {learning?.recommendation && <article className="profile-next"><span className="eyebrow">Следующая тренировка</span><h2>{learning.recommendation.scenarioTitle}</h2><button className="button primary" type="button" onClick={() => onStartRecommended(learning.recommendation.scenarioId)}>Начать <span aria-hidden="true">→</span></button></article>}
      <button className="profile-challenge-link" type="button" onClick={() => setProfileTab("challenges")}>Вызов дня и достижения <span aria-hidden="true">→</span></button>
    </>}
    {profileTab === "growth" && <LearningTrajectoryPanel dashboard={learning} notice={learningNotice} onDashboard={setLearning} onStartScenario={onStartRecommended} />}
    {profileTab === "challenges" && <MotivationPanel dashboard={motivation} loading={motivationLoading} notice={motivationNotice} onDashboard={setMotivation} onStartChallenge={onStartChallenge} onRetry={() => { setMotivationLoading(true); setMotivationRefreshKey((key) => key + 1); }} />}
    {profileTab === "history" && <>
      <section className="profile-section" aria-labelledby="history-title"><div className="section-heading"><div><h2 id="history-title">Переговоры</h2></div><span className="task-count">{history?.negotiations.length ?? 0}</span></div>{history === null && !notice ? <div className="history-grid"><div className="skeleton history-skeleton" /><div className="skeleton history-skeleton" /></div> : history?.negotiations.length ? <div className="history-grid">{history.negotiations.map((item) => <article className="history-card" key={item.sessionId}><div className="history-card-head"><span className={`history-status ${item.status}`}>{item.status === "active" ? "В процессе" : "Завершено"}</span><time>{date(item.createdAt)}</time></div><h3>{item.topic}</h3><div className="history-card-footer"><span>{item.score === null ? "Без оценки" : <><strong>{item.score}</strong>/100</>}</span><button className="button secondary" type="button" onClick={() => onOpenSession(item)}>{item.status === "active" ? "Продолжить" : "Разбор"}</button></div></article>)}</div> : <div className="profile-empty"><h3>История пока пуста</h3><p>Начните первую тренировку.</p></div>}</section>
      <details className="profile-section profile-review-disclosure"><summary>Мои рецензии · {history?.peerReviews.length ?? 0}</summary>{history?.peerReviews.length ? <div className="review-history-list">{history.peerReviews.map((item) => <article key={item.assignmentId}><div><strong>{item.scenarioTitle}</strong><span>{item.status === "submitted" ? "Рецензия отправлена" : "Черновик"} · {date(item.createdAt)}</span></div><b>{item.peerScore === null ? "—" : `${item.peerScore}/100`}</b></article>)}</div> : <p className="profile-muted">Рецензий пока нет.</p>}</details>
      <details className="danger-zone"><summary>Управление данными</summary><div><h2>Удалить аккаунт и мои данные</h2><p>Будут безвозвратно удалены профиль, ваши переговоры, отчёты и рецензии. Для подтверждения введите пароль.</p><form onSubmit={removeAccount}><label>Пароль<input type="password" autoComplete="current-password" required value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} /></label><button className="button danger" type="submit" disabled={deleting}>{deleting ? "Удаляем…" : "Удалить аккаунт"}</button></form></div></details>
    </>}
  </section></main>;
}

function MotivationPanel({ dashboard, loading, notice, onDashboard, onStartChallenge, onRetry }: { dashboard: MotivationDashboard | null; loading: boolean; notice: string; onDashboard: (value: MotivationDashboard) => void; onStartChallenge: (kind: "daily" | "weekly", scenarioId: string, topic: string) => Promise<string | null>; onRetry: () => void }) {
  const [busy, setBusy] = useState(false);
  const [actionNotice, setActionNotice] = useState("");
  const [teamName, setTeamName] = useState("");
  const [inviteCode, setInviteCode] = useState("");

  async function updatePreferences(enabled: boolean, teamOptIn: boolean) {
    setBusy(true); setActionNotice("");
    const result = await saveMotivationPreferences(enabled, teamOptIn);
    setBusy(false);
    if (!result.dashboard) { setActionNotice(result.error || "Не удалось сохранить настройки."); return; }
    onDashboard(result.dashboard);
  }
  async function teamAction(action: () => Promise<{ dashboard: MotivationDashboard | null; error?: string }>) {
    setBusy(true); setActionNotice("");
    const result = await action(); setBusy(false);
    if (!result.dashboard) { setActionNotice(result.error || "Не удалось обновить команду."); return; }
    onDashboard(result.dashboard); setTeamName(""); setInviteCode("");
  }
  async function launch(kind: "daily" | "weekly") {
    if (busy) return;
    setBusy(true); setActionNotice("");
    const challenge = kind === "daily" ? dashboard?.dailyChallenge : dashboard?.weeklyChallenge;
    if (!challenge) { setBusy(false); setActionNotice("Вызов временно недоступен."); return; }
    const error = await onStartChallenge(kind, challenge.scenarioId, challenge.scenarioTitle);
    setBusy(false);
    if (error) setActionNotice(error);
  }

  if (loading) return <section className="profile-section motivation-panel" aria-labelledby="motivation-title"><div className="skeleton motivation-skeleton" /></section>;
  if (!dashboard) return <section className="profile-section motivation-panel" aria-labelledby="motivation-title"><div className="section-heading"><div><span className="card-topline">По желанию</span><h2 id="motivation-title">Практика и вызовы</h2></div></div><div className="notice notice-error" role="alert">{notice || "Не удалось загрузить мотивационный профиль."}</div><button className="button secondary" type="button" onClick={onRetry}>Загрузить снова</button></section>;
  return <section className="profile-section motivation-panel" aria-labelledby="motivation-title">
    <div className="section-heading"><div><span className="card-topline">По желанию · можно отключить в любой момент</span><h2 id="motivation-title">Практика и вызовы</h2><p>Серии, личный skill tree и командные цели. Ваши сессии останутся в истории и после отключения.</p></div><label className="motivation-switch"><input type="checkbox" checked={dashboard.enabled} disabled={busy} onChange={(event) => void updatePreferences(event.target.checked, event.target.checked ? dashboard.teamOptIn : false)} /><span>{dashboard.enabled ? "Включено" : "Выключено"}</span></label></div>
    {actionNotice && <div className="notice notice-error compact" role="alert">{actionNotice}</div>}
    {!dashboard.enabled ? <div className="motivation-optin"><div><strong>Включите игровые механики</strong><p>Откройте ежедневные вызовы, отмечайте рост навыков и при желании участвуйте в командных челленджах.</p></div><button className="button primary" type="button" disabled={busy} onClick={() => void updatePreferences(true, false)}>{busy ? "Сохраняем…" : "Включить"}</button></div> : <>
      <div className="motivation-stats"><article><span>Текущая серия</span><strong>{dashboard.streak.current} {dashboard.streak.current === 1 ? "день" : "дней"}</strong><small>Личный рекорд: {dashboard.streak.longest}</small></article><article><span>Открыто навыков</span><strong>{dashboard.skillTree.filter((item) => item.unlocked).length}/{dashboard.skillTree.length}</strong><small>Сложность растёт постепенно</small></article><article><span>Достижения</span><strong>{dashboard.achievements.length}</strong><small>За конкретные действия</small></article></div>
      <div className="motivation-challenges"><article><span className="card-topline">Вызов дня · {new Date(`${dashboard.dailyChallenge.date}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}</span><h3>{dashboard.dailyChallenge.scenarioTitle}</h3><p>Навык: {coachSkillLabel[dashboard.dailyChallenge.skillId as CoachSkillId] ?? dashboard.dailyChallenge.skillId}</p><button className="button secondary" type="button" disabled={busy || dashboard.dailyChallenge.completed} onClick={() => void launch("daily")}>{busy ? "Готовим сценарий…" : dashboard.dailyChallenge.completed ? "Выполнено" : dashboard.dailyChallenge.sessionId ? "Продолжить вызов" : "Начать вызов"}</button></article><article><span className="card-topline">Командная неделя · с {new Date(`${dashboard.weeklyChallenge.weekStart}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}</span><h3>{dashboard.weeklyChallenge.scenarioTitle}</h3><p>Одинаковый seed для честного сравнения результата.</p><button className="button secondary" type="button" disabled={busy || !dashboard.teamOptIn || !dashboard.team || dashboard.weeklyChallenge.completed} onClick={() => void launch("weekly")}>{dashboard.weeklyChallenge.completed ? "Выполнено" : !dashboard.teamOptIn || !dashboard.team ? "Нужна команда и участие" : dashboard.weeklyChallenge.sessionId ? "Продолжить командный вызов" : "Начать командный вызов"}</button></article></div>
      <div className="motivation-tree"><div className="section-heading"><div><span className="card-topline">Дерево навыков</span><h3>Уровни навыков</h3></div></div><div className="motivation-tree-grid">{dashboard.skillTree.map((skill) => <article className={skill.unlocked ? "unlocked" : "locked"} key={skill.id}><div><strong>{skill.title}</strong><span>{skill.unlocked ? `Уровень ${skill.level}` : "Закрыто"}</span></div><p>{skill.unlocked ? skill.nextRequirement || "Навык открыт — продолжайте практику." : skill.unlockReason}</p></article>)}</div></div>
      <div className="motivation-lower"><section><div className="section-heading"><div><span className="card-topline">Конкретные действия</span><h3>Достижения</h3></div></div>{dashboard.achievements.length ? <ul className="achievement-list">{dashboard.achievements.map((item) => <li key={item.id}><span aria-hidden="true">✓</span><div><strong>{item.title}</strong><p>{item.description}</p></div><time>{new Date(item.earnedAt).toLocaleDateString("ru-RU")}</time></li>)}</ul> : <p className="profile-muted">Первое достижение появится после выполнения конкретного учебного действия.</p>}</section><section><div className="section-heading"><div><span className="card-topline">Добровольное участие</span><h3>Команда и рейтинг</h3></div></div><label className="team-optin"><input type="checkbox" checked={dashboard.teamOptIn} disabled={busy} onChange={(event) => void updatePreferences(true, event.target.checked)} /><span>Участвовать в командном рейтинге</span></label>{dashboard.team ? <div className="team-card"><div><strong>{dashboard.team.name}</strong><span>{dashboard.team.members} участников · код {dashboard.team.inviteCode}</span></div><button className="text-button" type="button" disabled={busy} onClick={() => void teamAction(leaveMotivationTeam)}>Покинуть</button></div> : <div className="team-forms"><form onSubmit={(event) => { event.preventDefault(); if (teamName.trim()) void teamAction(() => createMotivationTeam(teamName.trim())); }}><label>Создать команду<input maxLength={50} value={teamName} onChange={(event) => setTeamName(event.target.value)} placeholder="Название команды" /></label><button className="button secondary" type="submit" disabled={busy || !teamName.trim()}>Создать</button></form><form onSubmit={(event) => { event.preventDefault(); if (inviteCode.trim()) void teamAction(() => joinMotivationTeam(inviteCode.trim())); }}><label>Войти по коду<input maxLength={24} value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="Код приглашения" /></label><button className="button secondary" type="submit" disabled={busy || !inviteCode.trim()}>Войти</button></form></div>}{dashboard.teamOptIn && dashboard.leaderboard.length > 0 && <ol className="motivation-leaderboard" aria-label="Командный рейтинг">{dashboard.leaderboard.map((item) => <li key={item.teamId}><strong>#{item.rank} {item.teamName}</strong><span>{item.points} очков · {item.completedSessions} сессий</span></li>)}</ol>}{!dashboard.teamOptIn && <p className="profile-muted">Рейтинг скрыт. Включите участие, чтобы видеть таблицу без имён участников.</p>}</section></div>
    </>}
  </section>;
}

function LearningTrajectoryPanel({ dashboard, notice, onDashboard, onStartScenario }: { dashboard: LearningDashboard | null; notice: string; onDashboard: (value: LearningDashboard) => void; onStartScenario: (scenarioId: string) => void }) {
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [goalSkillId, setGoalSkillId] = useState("interests");
  const [targetScore, setTargetScore] = useState(80);
  const [weeklySessions, setWeeklySessions] = useState(2);
  const [savingGoal, setSavingGoal] = useState(false);
  const [drillResponse, setDrillResponse] = useState("");
  const [selfRating, setSelfRating] = useState(3);
  const [savingDrill, setSavingDrill] = useState(false);
  const [actionNotice, setActionNotice] = useState("");

  useEffect(() => {
    if (!dashboard) return;
    const focus = dashboard.goal?.skillId ?? dashboard.recommendation.skillId;
    setSelectedSkillId((current) => current && dashboard.skillMap.some((item) => item.id === current) ? current : focus);
    setGoalSkillId(dashboard.goal?.skillId ?? focus);
    setTargetScore(dashboard.goal?.targetScore ?? 80);
    setWeeklySessions(dashboard.goal?.weeklySessions ?? 2);
  }, [dashboard]);

  if (notice) return <section className="profile-section learning-shell" aria-labelledby="learning-title"><div className="notice notice-error" role="alert">Не удалось загрузить карту навыков: {notice}</div></section>;
  if (!dashboard) return <section className="profile-section learning-shell" aria-labelledby="learning-title"><div className="learning-skeleton"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div></section>;

  const selected = dashboard.skillMap.find((item) => item.id === selectedSkillId) ?? dashboard.skillMap[0];
  const recommended = dashboard.skillMap.find((item) => item.id === dashboard.recommendation.skillId) ?? dashboard.skillMap[0];
  const recommendedDrillId = dashboard.recommendedDrill.id;
  const shortDate = (value: string) => new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" }).format(new Date(value));

  async function submitGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingGoal) return;
    setSavingGoal(true);
    setActionNotice("");
    const result = await saveLearningGoal(goalSkillId, targetScore, weeklySessions);
    setSavingGoal(false);
    if (!result.dashboard) {
      setActionNotice(result.error || "Не удалось сохранить цель.");
      return;
    }
    onDashboard(result.dashboard);
    setSelectedSkillId(goalSkillId);
    setActionNotice("Личная цель сохранена. Рекомендации перестроены.");
  }

  async function submitDrill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingDrill || drillResponse.trim().length < 20) return;
    setSavingDrill(true);
    setActionNotice("");
    const result = await completeLearningDrill(recommendedDrillId, selfRating);
    setSavingDrill(false);
    if (!result.dashboard) {
      setActionNotice(result.error || "Не удалось сохранить упражнение.");
      return;
    }
    onDashboard(result.dashboard);
    setDrillResponse("");
    setActionNotice("Упражнение засчитано. Следующее повторение запланировано.");
  }

  return <section className="profile-section learning-shell" aria-labelledby="learning-title">
    <div className="section-heading learning-heading"><div><span className="card-topline">Персональная траектория</span><h2 id="learning-title">Карта переговорных навыков</h2><p>Каждый показатель рассчитан отдельно по последней сопоставимой попытке.</p></div><div className="rubric-chip"><span>Рубрика</span><strong>{dashboard.rubricVersion ?? "нет данных"}</strong><small>{dashboard.comparableSessions} сопоставимых</small></div></div>
    {dashboard.excludedIncompatibleSessions > 0 && <div className="compatibility-note" role="note">{dashboard.excludedIncompatibleSessions} прошлых попыток не включены в динамику: они оценены другой версией рубрики.</div>}
    {actionNotice && <div className={`notice compact ${actionNotice.includes("Не удалось") ? "notice-error" : "notice-success"}`} role="status">{actionNotice}</div>}

    <div className="learning-top-grid">
      <article className="recommendation-card"><span className="card-topline">Следующая тренировка · {recommended.title}</span><h3>{dashboard.recommendation.scenarioTitle}</h3><p>{dashboard.recommendation.reason}</p><button className="button primary" type="button" onClick={() => onStartScenario(dashboard.recommendation.scenarioId)}>Начать рекомендуемый кейс <span aria-hidden="true">→</span></button></article>
      <form className="goal-card" onSubmit={submitGoal}><span className="card-topline">Личная цель</span><h3>{dashboard.goal ? "Скорректировать фокус" : "Выберите навык для роста"}</h3><label>Навык<select value={goalSkillId} onChange={(event) => setGoalSkillId(event.target.value)}>{dashboard.skillMap.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><div className="goal-inline"><label>Цель<input type="number" min={40} max={100} value={targetScore} onChange={(event) => setTargetScore(Number(event.target.value))} /><span>/100</span></label><label>Практик в неделю<select value={weeklySessions} onChange={(event) => setWeeklySessions(Number(event.target.value))}>{[1, 2, 3, 4, 5, 6, 7].map((value) => <option value={value} key={value}>{value}</option>)}</select></label></div><button className="button secondary" type="submit" disabled={savingGoal}>{savingGoal ? "Сохраняем…" : dashboard.goal ? "Обновить цель" : "Поставить цель"}</button></form>
    </div>

    <div className="skill-map" aria-label="Восемь переговорных навыков">{dashboard.skillMap.map((skill) => <button type="button" className={`skill-card ${selected.id === skill.id ? "selected" : ""}`} key={skill.id} onClick={() => setSelectedSkillId(skill.id)} aria-pressed={selected.id === skill.id} aria-label={`${skill.title}: ${skill.score ?? "ещё не измерен"} из 100`}><div className="skill-card-head"><span className={`skill-state ${skill.status}`}>{skill.status === "new" ? "Новый" : skill.status === "focus" ? "Фокус" : skill.status === "developing" ? "Развивается" : "Сильный"}</span>{skill.due && <span className="due-badge">Повторить</span>}</div><div className="skill-value"><strong>{skill.score ?? "—"}</strong><span>/100</span>{skill.delta !== null && <small className={skill.delta >= 0 ? "positive" : "negative"}>{skill.delta > 0 ? "+" : ""}{skill.delta}</small>}</div><h3>{skill.title}</h3><p>{skill.description}</p><div className="skill-bar" aria-hidden="true"><i style={{ width: `${skill.score ?? 0}%` }} /></div></button>)}</div>

    <div className="skill-evidence"><div><span className="card-topline">Почему такой показатель</span><h3>{selected.title}</h3><p>{selected.evidenceReason}</p></div><dl><div><dt>Попыток</dt><dd>{selected.attempts}</dd></div><div><dt>Последняя практика</dt><dd>{selected.lastPracticedAt ? shortDate(selected.lastPracticedAt) : "—"}</dd></div><div><dt>Повторение</dt><dd>{selected.nextDueAt ? (selected.due ? "сейчас" : shortDate(selected.nextDueAt)) : "после диагностики"}</dd></div></dl></div>

    <div className="learning-analysis-grid">
      <section className="trend-card" aria-labelledby="weekly-trend-title"><span className="card-topline">Не общий балл, а один навык</span><h3 id="weekly-trend-title">Динамика «{selected.title}» по неделям</h3>{dashboard.weeklyProgress.length ? <div className="weekly-bars">{dashboard.weeklyProgress.map((point) => <div key={point.periodStart}><span>{shortDate(point.periodStart)}</span><div><i style={{ width: `${point.scores[selected.id] ?? 0}%` }} /></div><strong>{point.scores[selected.id] ?? "—"}</strong><small>{point.attempts}×</small></div>)}</div> : <p className="profile-muted">Завершите первую тренировку — здесь появится недельная динамика.</p>}</section>
      <section className="trend-card" aria-labelledby="scenario-trend-title"><span className="card-topline">Переносимость навыка</span><h3 id="scenario-trend-title">«{selected.title}» по сценариям</h3>{dashboard.scenarioProgress.length ? <div className="scenario-skill-list">{dashboard.scenarioProgress.map((item) => <div key={item.scenarioId}><div><strong>{item.scenarioTitle}</strong><span>{item.attempts} попыт.</span></div><b>{item.scores[selected.id] ?? "—"}<small>/100</small></b></div>)}</div> : <p className="profile-muted">После практики сравним навык в разных переговорных контекстах.</p>}</section>
    </div>

    <form className="drill-card" onSubmit={submitDrill}><div className="drill-meta"><span className="card-topline">Микроупражнение · {dashboard.recommendedDrill.durationMinutes} минуты</span><h3>{dashboard.recommendedDrill.title}</h3><p>{dashboard.recommendedDrill.prompt}</p><ol>{dashboard.recommendedDrill.instructions.map((item) => <li key={item}>{item}</li>)}</ol></div><div className="drill-work"><label htmlFor="drill-answer">Ваша реплика<textarea id="drill-answer" rows={5} minLength={20} maxLength={1000} value={drillResponse} onChange={(event) => setDrillResponse(event.target.value)} placeholder="Сформулируйте ответ своими словами…" required /></label><details><summary>Открыть чек-лист и шаблон</summary><ul>{dashboard.recommendedDrill.successChecklist.map((item) => <li key={item}>{item}</li>)}</ul><blockquote>{dashboard.recommendedDrill.suggestedTemplate}</blockquote></details><label className="rating-label">Насколько уверенно получилось?<select value={selfRating} onChange={(event) => setSelfRating(Number(event.target.value))}><option value={1}>1 — нужно повторить</option><option value={2}>2 — пока трудно</option><option value={3}>3 — получилось частично</option><option value={4}>4 — уверенно</option><option value={5}>5 — легко</option></select></label><button className="button primary" type="submit" disabled={savingDrill || drillResponse.trim().length < 20}>{savingDrill ? "Сохраняем…" : "Завершить и запланировать повтор"}</button></div></form>
  </section>;
}

function ConfigureScreen({ scenario, initial, onBack, onContinue }: { scenario: Scenario; initial: SessionConfiguration; onBack: () => void; onContinue: (value: SessionConfiguration) => void }) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState("");
  const update = (key: keyof SessionConfiguration, next: string | number) => {
    setValue((current) => ({ ...current, [key]: next } as SessionConfiguration));
    setError("");
  };
  const updateSimulation = <K extends keyof SessionConfiguration["simulation"]>(key: K, next: SessionConfiguration["simulation"][K]) => {
    setValue((current) => ({ ...current, simulation: { ...current.simulation, [key]: next } }));
    setError("");
  };
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = {
      ...value,
      topic: value.topic.trim(),
      context: value.context.trim(),
      participantRole: value.participantRole.trim(),
      opponentRole: value.opponentRole.trim(),
      objective: value.objective.trim(),
    };
    const lengths = [normalized.topic.length >= 3, normalized.context.length >= 10, normalized.participantRole.length >= 2, normalized.opponentRole.length >= 2, normalized.objective.length >= 5];
    if (!lengths.every(Boolean) || normalized.maxTurns < 6 || normalized.maxTurns > 20) {
      setError("Проверьте заполнение полей: контекст — от 10 символов, цель — от 5, лимит — от 6 до 20 ходов.");
      return;
    }
    setError("");
    onContinue(normalized);
  }
  const reset = () => { setValue(defaultConfiguration(scenario)); setError(""); };

  return (
    <main className="app-shell">
      <Topbar step="configure" />
      <section className="workspace configure" id="main-content" aria-labelledby="configure-title">
        <button className="back-button" type="button" onClick={onBack}>← К сценариям</button>
        <div className="eyebrow">Персональная тренировка · {scenario.title}</div>
        <h1 id="configure-title">Настройте переговоры под себя</h1>
        <p className="lead">Настройте ситуацию, роли и сложность.</p>
        <form className="configure-layout" onSubmit={submit} noValidate>
          <div className="configure-form">
            <section className="configure-section" aria-labelledby="situation-title">
              <div className="configure-section-heading"><span>01</span><div><h2 id="situation-title">Ситуация</h2></div></div>
              <label htmlFor="config-topic">Тема переговоров<input id="config-topic" value={value.topic} minLength={3} maxLength={120} placeholder="Например, ресурсы для запуска сервиса" onChange={(event) => update("topic", event.target.value)} required /></label>
              <label htmlFor="config-context">Публичный контекст<textarea id="config-context" rows={4} value={value.context} minLength={10} maxLength={1200} placeholder="Что произошло и почему сторонам важно договориться?" onChange={(event) => update("context", event.target.value)} required /><small>{value.context.length}/1200 · не указывайте скрытые границы второй стороны</small></label>
            </section>

            <section className="configure-section" aria-labelledby="roles-title">
              <div className="configure-section-heading"><span>02</span><div><h2 id="roles-title">Роли и цель</h2></div></div>
              <div className="configure-two-columns">
                <label htmlFor="config-participant-role">Моя роль<input id="config-participant-role" value={value.participantRole} minLength={2} maxLength={100} placeholder="Руководитель проекта" onChange={(event) => update("participantRole", event.target.value)} required /></label>
                <label htmlFor="config-opponent-role">Роль оппонента<input id="config-opponent-role" value={value.opponentRole} minLength={2} maxLength={100} placeholder="Директор подразделения" onChange={(event) => update("opponentRole", event.target.value)} required /></label>
              </div>
              <label htmlFor="config-objective">Моя цель<textarea id="config-objective" rows={3} value={value.objective} minLength={5} maxLength={500} placeholder="Какого измеримого результата вы хотите добиться?" onChange={(event) => update("objective", event.target.value)} required /><small>{value.objective.length}/500</small></label>
            </section>

            <section className="configure-section" aria-labelledby="behavior-title">
              <div className="configure-section-heading"><span>03</span><div><h2 id="behavior-title">Оппонент</h2></div></div>
              <fieldset><legend>Сложность</legend><div className="configuration-options">{difficultyOptions.map((option) => <button type="button" title={option.description} className={`configuration-option ${value.difficulty === option.value ? "active" : ""}`} aria-pressed={value.difficulty === option.value} onClick={() => update("difficulty", option.value)} key={option.value}><strong>{option.label}</strong></button>)}</div></fieldset>
              <fieldset><legend>Тон</legend><div className="configuration-options">{toneOptions.map((option) => <button type="button" title={option.description} className={`configuration-option ${value.tone === option.value ? "active" : ""}`} aria-pressed={value.tone === option.value} onClick={() => update("tone", option.value)} key={option.value}><strong>{option.label}</strong></button>)}</div></fieldset>
              <label className="turn-limit" htmlFor="config-turns"><span>Максимум ходов <output htmlFor="config-turns">{value.maxTurns}</output></span><input id="config-turns" type="range" min="6" max="20" step="1" value={value.maxTurns} onChange={(event) => update("maxTurns", Number(event.target.value))} /></label>
            </section>
            <details className="configure-section simulation-config configure-advanced">
              <summary><span>04</span><div><strong>Дополнительные параметры</strong></div></summary>
              <div className="configure-two-columns">
                <label>Стратегия ведущего оппонента<select value={value.simulation.opponentStrategy} onChange={(event) => updateSimulation("opponentStrategy", event.target.value as SessionConfiguration["simulation"]["opponentStrategy"])}><option value="analytical">Аналитическая</option><option value="collaborative">Партнёрская</option><option value="competitive">Конкурентная</option><option value="cautious">Осторожная</option></select></label>
                <label>AI-участников<select value={value.simulation.aiParticipants} onChange={(event) => updateSimulation("aiParticipants", Number(event.target.value) as 1 | 2 | 3)}><option value={1}>1 — основной оппонент</option><option value={2}>2 — + финансовый контролёр</option><option value={3}>3 — + руководитель исполнения</option></select></label>
                <label>Неожиданные события<select value={value.simulation.eventIntensity} onChange={(event) => updateSimulation("eventIntensity", Number(event.target.value) as 0 | 1 | 2)}><option value={0}>Отключены</option><option value={1}>1 событие</option><option value={2}>2 события</option></select></label>
                <label>Время на решение<select value={value.simulation.decisionTimeSeconds} onChange={(event) => updateSimulation("decisionTimeSeconds", Number(event.target.value))}><option value={0}>Без таймера</option><option value={45}>45 секунд</option><option value={90}>90 секунд</option><option value={120}>2 минуты</option></select></label>
                <label>Seed для повторения<input type="number" min={0} max={2147483647} placeholder="Случайный" value={value.simulation.seed ?? ""} onChange={(event) => updateSimulation("seed", event.target.value ? Number(event.target.value) : null)} /><small>Одинаковый seed воспроизводит события.</small></label>
              </div>
              <div className="simulation-safety"><span aria-hidden="true">◇</span><p><strong>ZOPA защищена.</strong> События влияют на давление, полномочия и контекст, но не подменяют reservation points.</p></div>
            </details>
            {error && <p className="field-error" role="alert">{error}</p>}
          </div>

          <aside className="configuration-summary" aria-label="Сводка настройки">
            <span className="card-topline">Будущая сессия</span><h2>{value.topic || "Без темы"}</h2><p>{value.participantRole || "Ваша роль"} ↔ {value.opponentRole || "Оппонент"}</p>
            <dl><div><dt>Сложность</dt><dd>{difficultyLabel[value.difficulty]}</dd></div><div><dt>Тон</dt><dd>{toneLabel[value.tone]}</dd></div><div><dt>Лимит</dt><dd>{value.maxTurns} ходов</dd></div></dl>
            <div className="configuration-note"><strong>Условия сделки защищены</strong></div>
            <button className="button primary" type="submit">Перейти к брифингу <span aria-hidden="true">→</span></button>
            <button className="button ghost" type="button" onClick={reset}>Вернуть настройки сценария</button>
          </aside>
        </form>
      </section>
    </main>
  );
}

function Briefing({ scenario, onBack, onStart, configuration, format, isCustom, isStarting, backLabel }: { scenario: Scenario; onBack: () => void; onStart: () => void; configuration: SessionConfiguration; format: ConversationFormat; isCustom: boolean; isStarting: boolean; backLabel: string }) {
  const conditions = scenario.tasks.filter((task) => task.title.trim().toLocaleLowerCase("ru") !== configuration.objective.trim().toLocaleLowerCase("ru"));
  return (
    <main className="app-shell">
      <Topbar step="brief" />
      <section className="workspace briefing" id="main-content" aria-labelledby="brief-title">
        <button className="back-button" onClick={onBack}>{backLabel}</button>
        <div className="eyebrow">Ваша роль · {configuration.participantRole}</div>
        <h1 id="brief-title">{configuration.topic}</h1>
        <p className="lead">{configuration.context}</p>
        <div className="brief-badges" aria-label="Параметры тренировки">
          <span>{format === "call" ? "Голосовой звонок" : "Текстовый диалог"}</span>
          <span>{scenario.duration}</span>
          {isCustom && <><span>{difficultyLabel[configuration.difficulty]}</span><span>{toneLabel[configuration.tone]} тон</span><span>до {configuration.maxTurns} ходов</span></>}
        </div>
        <div className="brief-grid">
          <article className="panel">
            <h2>Ваша цель</h2>
            <p>{configuration.objective}</p>
            {conditions.length > 0 && <><h2>Условия сделки</h2><ul className="brief-task-list">{conditions.map((task) => <li key={task.id}><strong>{task.title}</strong></li>)}</ul></>}
          </article>
          <aside className="panel quiet">
            <span className="card-topline">Оппонент</span>
            <h2>{configuration.opponentRole}</h2>
            <div className="tag-list">{scenario.skills.map((skill) => <span className="tag" key={skill}>{skill}</span>)}</div>
          </aside>
        </div>
        <button className="button primary" disabled={isStarting} onClick={onStart}>{isStarting ? "Создаём сессию…" : isCustom ? "К личной подготовке" : "Начать переговоры"} <span aria-hidden="true">→</span></button>
      </section>
    </main>
  );
}

function PrebriefScreen({ sessionId, attemptNumber, configuration, onContinue }: { sessionId: string; attemptNumber: number; configuration: SessionConfiguration; onContinue: () => void }) {
  const [value, setValue] = useState<PrebriefWorksheetInput>({
    focusSkill: "interests",
    goal: configuration.objective,
    interests: [],
    participantBatna: "Определить лучшую альтернативу, если договориться не получится.",
    participantReservation: "Зафиксировать собственную минимально допустимую границу до диалога.",
    plannedQuestions: ["Что для вас важнее всего в этом соглашении и почему?"],
  });
  const [interestsText, setInterestsText] = useState("");
  const [questionsText, setQuestionsText] = useState(value.plannedQuestions.join("\n"));
  const [status, setStatus] = useState<"loading" | "ready" | "saving" | "error">("loading");
  const [notice, setNotice] = useState("");
  const [inheritedAttempt, setInheritedAttempt] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    getCoachPrebrief(sessionId).then((result) => {
      if (!active) return;
      if (!result.worksheet) { setStatus("error"); setNotice(result.error || "Не удалось загрузить лист подготовки."); return; }
      const worksheet = result.worksheet;
      setValue({ focusSkill: worksheet.focusSkill, goal: worksheet.goal, interests: worksheet.interests, participantBatna: worksheet.participantBatna, participantReservation: worksheet.participantReservation, plannedQuestions: worksheet.plannedQuestions });
      setInterestsText(worksheet.interests.join("\n"));
      setQuestionsText(worksheet.plannedQuestions.join("\n"));
      setInheritedAttempt(worksheet.inheritedFromAttempt);
      setStatus("ready");
    });
    return () => { active = false; };
  }, [sessionId]);

  const lines = (text: string) => text.split("\n").map((item) => item.trim()).filter(Boolean).slice(0, 6);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "saving") return;
    const prepared = { ...value, interests: lines(interestsText), plannedQuestions: lines(questionsText) };
    if (!prepared.plannedQuestions.length) { setNotice("Добавьте хотя бы один вопрос для проверки интересов."); return; }
    setStatus("saving"); setNotice("");
    const result = await saveCoachPrebrief(sessionId, prepared);
    if (!result.worksheet) { setStatus("error"); setNotice(result.error || "Не удалось сохранить подготовку."); return; }
    setStatus("ready");
    onContinue();
  }

  return <main className="app-shell"><Topbar step="prebrief" /><section className="workspace prebrief-workspace" id="main-content" aria-labelledby="prebrief-title">
    <header className="prebrief-hero"><div><div className="eyebrow">Подготовка · попытка {attemptNumber}</div><h1 id="prebrief-title">Ваш план переговоров</h1><p className="lead">План виден только вам.</p></div><button className="button secondary" type="button" onClick={onContinue}>Пропустить и начать →</button></header>
    {inheritedAttempt && <div className="notice" role="status">План перенесён из попытки {inheritedAttempt}. Обновите его с учётом прошлого разбора.</div>}
    {notice && <div className="notice notice-error" role="alert">{notice}</div>}
    {status === "loading" ? <div className="prebrief-grid"><div className="skeleton prebrief-skeleton" /><div className="skeleton prebrief-skeleton" /></div> : <form className="prebrief-grid" onSubmit={submit}>
      <div className="prebrief-form panel">
        <label>Навык в фокусе<select value={value.focusSkill} onChange={(event) => setValue((current) => ({ ...current, focusSkill: event.target.value as CoachSkillId }))}>{coachSkillOptions.map((item) => <option value={item.value} key={item.value}>{item.label} — {item.cue}</option>)}</select></label>
        <label>Цель переговоров<textarea rows={3} minLength={5} maxLength={500} required value={value.goal} onChange={(event) => setValue((current) => ({ ...current, goal: event.target.value }))} /></label>
        <label>Мои интересы<textarea rows={4} maxLength={800} value={interestsText} onChange={(event) => setInterestsText(event.target.value)} placeholder="По одному на строку" /></label>
        <div className="prebrief-two"><label>Моя BATNA<textarea rows={4} minLength={5} maxLength={500} required value={value.participantBatna} onChange={(event) => setValue((current) => ({ ...current, participantBatna: event.target.value }))} /></label><label>Моя граница<textarea rows={4} minLength={5} maxLength={500} required value={value.participantReservation} onChange={(event) => setValue((current) => ({ ...current, participantReservation: event.target.value }))} /></label></div>
        <label>План вопросов<textarea rows={5} maxLength={1000} required value={questionsText} onChange={(event) => setQuestionsText(event.target.value)} placeholder="По одному вопросу на строку" /></label>
      </div>
      <aside className="prebrief-guide panel quiet"><span className="card-topline">Личный план</span><h2>{coachSkillLabel[value.focusSkill]}</h2><p>BATNA, граница и вопросы не раскрываются оппоненту.</p><button className="button primary" type="submit" disabled={status === "saving"}>{status === "saving" ? "Сохраняем…" : "Сохранить и начать"}</button></aside>
    </form>}
  </section></main>;
}

type SpeechRecognitionResultLike = { isFinal: boolean; 0: { transcript: string } };
type SpeechRecognitionEventLike = Event & { resultIndex: number; results: { length: number; [index: number]: SpeechRecognitionResultLike } };
type SpeechRecognitionLike = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: Event & { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void; stop: () => void;
};
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;
declare global { interface Window { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor } }

function VoiceCapture({ messages, draft, disabled, value, notice, onDraft, onVoiceDraft }: { messages: ChatMessage[]; draft: string; disabled: boolean; value: VoiceDraft | null; notice: string; onDraft: (value: string) => void; onVoiceDraft: (value: VoiceDraft | null) => void }) {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [consentOpen, setConsentOpen] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  const [retention, setRetention] = useState<VoiceDraft["retentionPolicy"]>("do_not_store");
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [interim, setInterim] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [ttsSpeaking, setTtsSpeaking] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const finalTranscriptRef = useRef("");
  const transcriptRef = useRef(draft);
  const activeRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const limitRef = useRef<number | null>(null);
  const frameRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const metricsRef = useRef({ pauseCount: 0, longestPauseMs: 0, interruptionCount: 0, silenceStartedAt: 0, speechSeen: false });
  const spokenIdsRef = useRef(new Set(messages.map((item) => item.id)));

  useEffect(() => {
    const speech = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    setSupported(Boolean(window.isSecureContext && speech && typeof navigator.mediaDevices?.getUserMedia === "function" && "MediaRecorder" in window));
    return () => {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      recognitionRef.current?.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (timerRef.current) window.clearInterval(timerRef.current);
      if (limitRef.current) window.clearTimeout(limitRef.current);
      if (frameRef.current) window.cancelAnimationFrame(frameRef.current);
      void audioContextRef.current?.close();
    };
  }, []);

  useEffect(() => {
    const newReplies = messages.filter((item) => item.author === "opponent" && !spokenIdsRef.current.has(item.id));
    messages.forEach((item) => spokenIdsRef.current.add(item.id));
    if (!ttsEnabled || !newReplies.length || !window.speechSynthesis) return;
    setTtsSpeaking(true);
    newReplies.forEach((item, index) => {
      const utterance = new SpeechSynthesisUtterance(item.text);
      utterance.lang = "ru-RU";
      utterance.rate = 1;
      if (index === newReplies.length - 1) utterance.onend = () => setTtsSpeaking(false);
      utterance.onerror = () => setTtsSpeaking(false);
      window.speechSynthesis.speak(utterance);
    });
  }, [messages, ttsEnabled]);

  function stopCapture() {
    activeRef.current = false;
    setRecording(false);
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (limitRef.current) window.clearTimeout(limitRef.current);
    if (frameRef.current) window.cancelAnimationFrame(frameRef.current);
    timerRef.current = null;
    limitRef.current = null;
    frameRef.current = null;
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
  }

  async function startCapture() {
    const SpeechRecognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!supported || !SpeechRecognition) {
      setVoiceError("Голос недоступен в этом браузере или без HTTPS. Текстовый ввод продолжает работать.");
      return;
    }
    try {
      setVoiceError("");
      onVoiceDraft(null);
      if (window.speechSynthesis?.speaking) {
        window.speechSynthesis.cancel();
        setTtsSpeaking(false);
        metricsRef.current.interruptionCount = 1;
      } else {
        metricsRef.current.interruptionCount = 0;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      streamRef.current = stream;
      chunksRef.current = [];
      finalTranscriptRef.current = "";
      transcriptRef.current = draft;
      metricsRef.current = { ...metricsRef.current, pauseCount: 0, longestPauseMs: 0, silenceStartedAt: performance.now(), speechSeen: false };
      startedAtRef.current = performance.now();
      setElapsedMs(0);
      setInterim("");

      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((item) => MediaRecorder.isTypeSupported(item)) ?? "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const durationMs = Math.max(100, Math.min(120000, Math.round(performance.now() - startedAtRef.current)));
        const words = transcriptRef.current.trim().split(/\s+/).filter(Boolean).length;
        const speakingRateWpm = Math.min(400, Math.round(words / Math.max(durationMs / 60000, 1 / 60)));
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (blob.size) onVoiceDraft({ blob, mimeType: blob.type || "audio/webm", durationMs, retentionPolicy: retention, observations: { pauseCount: metricsRef.current.pauseCount, longestPauseMs: metricsRef.current.longestPauseMs, speakingRateWpm, interruptionCount: metricsRef.current.interruptionCount } });
      };
      recorder.start(250);

      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "ru-RU";
      recognition.onresult = (event) => {
        let interimText = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          if (result.isFinal) finalTranscriptRef.current += `${result[0].transcript} `;
          else interimText += result[0].transcript;
        }
        const combined = `${finalTranscriptRef.current}${interimText}`.trim();
        transcriptRef.current = combined;
        setInterim(interimText);
        if (combined) onDraft(combined);
      };
      recognition.onerror = (event) => {
        setVoiceError(`Распознавание остановлено${event.error ? `: ${event.error}` : ""}. Уже распознанный текст сохранён — его можно исправить или отправить вручную.`);
        stopCapture();
      };
      recognition.onend = () => { if (activeRef.current) stopCapture(); };
      recognitionRef.current = recognition;

      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      const levels = new Uint8Array(analyser.fftSize);
      const sampleLevel = () => {
        if (!activeRef.current) return;
        analyser.getByteTimeDomainData(levels);
        let sum = 0;
        for (const level of levels) { const value = (level - 128) / 128; sum += value * value; }
        const speaking = Math.sqrt(sum / levels.length) > 0.035;
        const now = performance.now();
        if (speaking) {
          const silence = now - metricsRef.current.silenceStartedAt;
          if (metricsRef.current.speechSeen && silence >= 700) {
            metricsRef.current.pauseCount += 1;
            metricsRef.current.longestPauseMs = Math.max(metricsRef.current.longestPauseMs, Math.round(silence));
          }
          metricsRef.current.speechSeen = true;
          metricsRef.current.silenceStartedAt = now;
        } else if (!metricsRef.current.silenceStartedAt) metricsRef.current.silenceStartedAt = now;
        frameRef.current = window.requestAnimationFrame(sampleLevel);
      };

      activeRef.current = true;
      setRecording(true);
      recognition.start();
      sampleLevel();
      timerRef.current = window.setInterval(() => setElapsedMs(Math.round(performance.now() - startedAtRef.current)), 250);
      limitRef.current = window.setTimeout(() => { setVoiceError("Достигнут лимит одной реплики — 2 минуты. Расшифровка сохранена для редактирования."); stopCapture(); }, 120000);
    } catch (cause) {
      setVoiceError(cause instanceof Error ? `Микрофон не запущен: ${cause.message}. Текстовый ввод доступен.` : "Микрофон не запущен. Текстовый ввод доступен.");
      stopCapture();
    }
  }

  function requestCapture() {
    if (recording) { stopCapture(); return; }
    if (!consentChecked) { setConsentOpen(true); return; }
    void startCapture();
  }

  const duration = recording ? elapsedMs : value?.durationMs ?? 0;
  return <>
    <section className={`voice-console ${recording ? "recording" : ""}`} aria-label="Голосовой режим">
      <div className="voice-primary"><button className="voice-mic" type="button" onClick={requestCapture} disabled={disabled || supported === false} aria-label={recording ? "Остановить запись" : "Начать голосовую реплику"}><span aria-hidden="true">{recording ? "■" : "●"}</span></button><div><strong>{recording ? "Слушаю и расшифровываю…" : value ? "Голосовая реплика готова" : "Голосовой режим"}</strong><p>{supported === false ? "Нужны Chrome/Edge и защищённое HTTPS-соединение. Можно продолжить текстом." : recording ? "Остановите запись, проверьте текст ниже и только затем отправьте." : "Запись не отправится без вашей проверки."}</p></div></div>
      <div className="voice-timer"><span>{Math.floor(duration / 60000)}:{String(Math.floor(duration / 1000) % 60).padStart(2, "0")}</span><small>{recording ? "идёт запись" : value ? "длительность" : "до 2:00"}</small></div>
      <button className={`voice-tts ${ttsEnabled ? "active" : ""}`} type="button" onClick={() => { if (ttsEnabled) { window.speechSynthesis?.cancel(); setTtsSpeaking(false); } setTtsEnabled(!ttsEnabled); }} disabled={disabled}><span aria-hidden="true">◖))</span>{ttsSpeaking ? "Остановить голос" : ttsEnabled ? "Ответы озвучиваются" : "Озвучивать ответы"}</button>
      {(value || recording) && <div className="voice-observations"><span>Паузы <b>{value?.observations.pauseCount ?? metricsRef.current.pauseCount}</b></span><span>Темп <b>{value?.observations.speakingRateWpm ?? "—"} слов/мин</b></span><span>Перебивания <b>{value?.observations.interruptionCount ?? metricsRef.current.interruptionCount}</b></span><span>Хранение <b>{{ do_not_store: "не хранить", "24_hours": "24 часа", "30_days": "30 дней" }[value?.retentionPolicy ?? retention]}</b></span></div>}
      {interim && recording && <p className="voice-live" aria-live="polite">Распознаём: {interim}</p>}
      {(voiceError || notice) && <p className={voiceError ? "voice-error" : "voice-notice"} role="status">{voiceError || notice}</p>}
    </section>
    {consentOpen && <div className="modal-backdrop" role="presentation"><section className="voice-consent" role="dialog" aria-modal="true" aria-labelledby="voice-consent-title"><span className="card-topline">Контроль приватности</span><h2 id="voice-consent-title">Разрешить голосовую реплику?</h2><p>Браузер получит доступ к микрофону и выполнит потоковую расшифровку. Мы не определяем эмоции, личность или состояние по голосу.</p><label className="consent-check"><input type="checkbox" checked={consentChecked} onChange={(event) => setConsentChecked(event.target.checked)} /><span>Я согласен на обработку аудио и расшифровки для этой тренировки.</span></label><label className="retention-select">Что делать с записью<select value={retention} onChange={(event) => setRetention(event.target.value as VoiceDraft["retentionPolicy"])}><option value="do_not_store">Не хранить после отправки</option><option value="24_hours">Хранить 24 часа</option><option value="30_days">Хранить 30 дней</option></select></label><div className="voice-consent-actions"><button className="button ghost" type="button" onClick={() => setConsentOpen(false)}>Отмена</button><button className="button primary" type="button" disabled={!consentChecked} onClick={() => { setConsentOpen(false); void startCapture(); }}>Разрешить и начать</button></div><small>Запись можно удалить отдельно от текста в любой момент.</small></section></div>}
  </>;
}

function Chat({ sessionId, scenario, configuration, preferredFormat, attemptNumber, messages, simulation, onSimulation, draft, isReplying, isFinishing, isTerminal, sent, notice, failedMessage, voiceDraft, voiceRecordings, voiceNotice, onDraft, onVoiceDraft, onDeleteVoice, onSend, onAutoTurn, onRetryMessage, onFinish }: { sessionId: string | null; scenario: Scenario; configuration: SessionConfiguration; preferredFormat: ConversationFormat; attemptNumber: number; messages: ChatMessage[]; simulation: SimulationSnapshot | null; onSimulation: (value: SimulationSnapshot) => void; draft: string; isReplying: boolean; isFinishing: boolean; isTerminal: boolean; sent: boolean; notice: string; failedMessage: string | null; voiceDraft: VoiceDraft | null; voiceRecordings: VoiceRecording[]; voiceNotice: string; onDraft: (value: string) => void; onVoiceDraft: (value: VoiceDraft | null) => void; onDeleteVoice: (recordingId: string) => void; onSend: (event: FormEvent<HTMLFormElement>) => void; onAutoTurn: (text: string) => Promise<MessageResult | null>; onRetryMessage: () => void; onFinish: () => void }) {
  const [hint, setHint] = useState<CoachHint | null>(null);
  const [hintLoading, setHintLoading] = useState(false);
  const [coachNotice, setCoachNotice] = useState("");
  const [rewriteTarget, setRewriteTarget] = useState<ChatMessage | null>(null);
  const [rewriteText, setRewriteText] = useState("");
  const [rewrite, setRewrite] = useState<CoachRewrite | null>(null);
  const [rewriteLoading, setRewriteLoading] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [hypothesisText, setHypothesisText] = useState("");
  const [hypothesisLoading, setHypothesisLoading] = useState(false);
  const [hypothesisNotice, setHypothesisNotice] = useState("");
  const [useBackupCall, setUseBackupCall] = useState(false);
  const [liveActive, setLiveActive] = useState(false);
  const composerDisabled = isReplying || isFinishing || isTerminal || liveActive;
  const lastParticipant = [...messages].reverse().find((item) => item.author === "user") ?? null;
  const phases: Array<{ id: SimulationSnapshot["phase"]; label: string }> = [{ id: "preparation", label: "Подготовка" }, { id: "opening", label: "Открытие" }, { id: "exploration", label: "Исследование" }, { id: "exchange", label: "Обмен" }, { id: "commitment", label: "Фиксация" }];
  const activePhase = phases.findIndex((item) => item.id === simulation?.phase);
  const timerWaitingForReply = !isTerminal && secondsLeft === null && Boolean(simulation?.decisionTimeSeconds);

  useEffect(() => {
    if (!simulation?.deadlineAt || isTerminal) { setSecondsLeft(null); return; }
    const observedAt = Date.now();
    const remainingAtObservation = Math.max(0, Math.min(
      simulation.decisionTimeSeconds * 1000,
      new Date(simulation.deadlineAt).getTime() - new Date(simulation.serverTime).getTime(),
    ));
    const refresh = () => setSecondsLeft(Math.max(0, Math.ceil((remainingAtObservation - (Date.now() - observedAt)) / 1000)));
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, [simulation?.deadlineAt, simulation?.serverTime, isTerminal]);

  async function testHypothesis(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || hypothesisLoading || hypothesisText.trim().length < 5) return;
    setHypothesisLoading(true); setHypothesisNotice("");
    const result = await checkSimulationHypothesis(sessionId, hypothesisText.trim());
    setHypothesisLoading(false);
    if (!result.hypothesis || !result.simulation) { setHypothesisNotice(result.error || "Недостаточно данных для проверки."); return; }
    onSimulation(result.simulation); setHypothesisText("");
  }

  async function askHint() {
    if (!sessionId || hintLoading || composerDisabled) return;
    setHintLoading(true); setCoachNotice("");
    const result = await requestCoachHint(sessionId, draft);
    setHintLoading(false);
    if (!result.hint) { setCoachNotice(result.error || "Тренер временно недоступен."); return; }
    setHint(result.hint);
  }

  function openRewrite(message: ChatMessage) {
    setRewriteTarget(message); setRewriteText(message.text); setRewrite(null); setCoachNotice("");
  }

  async function analyzeRewrite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || !rewriteTarget || rewriteLoading || rewriteText.trim().length < 5) return;
    setRewriteLoading(true); setCoachNotice("");
    const result = await requestCoachRewrite(sessionId, rewriteTarget.id, rewriteText.trim());
    setRewriteLoading(false);
    if (!result.rewrite) { setCoachNotice(result.error || "Не удалось построить альтернативную ветку."); return; }
    setRewrite(result.rewrite);
  }

  const composer = <><form className="composer" onSubmit={onSend}><label className="sr-only" htmlFor="message">Ваше сообщение</label><textarea id="message" rows={2} maxLength={4000} value={draft} onChange={(event) => onDraft(event.target.value)} onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") event.currentTarget.form?.requestSubmit(); }} aria-describedby="composer-hint" placeholder={isTerminal ? "Сессия завершена" : "Напишите ответ…"} disabled={composerDisabled} /><button className="button primary" type="submit" disabled={!draft.trim() || composerDisabled}>Отправить</button></form><p className="composer-help" id="composer-hint">{isTerminal ? "Сессия завершена. Перейдите к разбору, чтобы увидеть результат." : sent ? "Сообщение сохранено. Продолжайте диалог или завершите сессию. Ctrl + Enter — отправить." : "Ctrl + Enter — отправить сообщение."}</p></>;

  return <main className={`app-shell simulation-${simulation?.mode ?? "meeting"}`}><Topbar step="chat" /><section className="simulation-phasebar" aria-label="Фазы переговоров">{phases.map((phase, index) => <div className={`${index < activePhase ? "done" : index === activePhase ? "active" : ""}`} key={phase.id}><span>{index < activePhase ? "✓" : index + 1}</span><small>{phase.label}</small></div>)}<aside className={`decision-clock ${secondsLeft !== null && secondsLeft <= 15 ? "urgent" : ""}`}><span>{timerWaitingForReply ? "—" : secondsLeft === null ? "∞" : secondsLeft}</span><small>{timerWaitingForReply ? "после ответа" : secondsLeft === null ? "без таймера" : "секунд"}</small></aside></section><section className="chat-layout" id="main-content">
    <aside className="session-sidebar"><span className="card-topline">{preferredFormat === "call" ? "Голосовой звонок" : "Текстовый диалог"} · попытка {attemptNumber}</span><h1>{configuration.topic}</h1><p>{configuration.objective}</p><details className="session-details"><summary>Условия и участники</summary><div className="simulation-party-list">{(simulation?.opponents ?? []).map((opponent) => <article key={opponent.id}><span>{opponent.label.slice(0, 1)}</span><div><strong>{opponent.label}</strong><small>{opponent.role}</small></div></article>)}</div><div className="session-badges vertical"><span>{difficultyLabel[configuration.difficulty]}</span><span>до {configuration.maxTurns} ходов</span></div></details></aside>
    <section className="chat-panel" aria-label={`Диалог с ${configuration.opponentRole}`} aria-busy={isReplying}><div className="chat-header"><div><span className="online-dot" aria-hidden="true" />{configuration.opponentRole}</div><span className="chat-format-label">{preferredFormat === "call" ? "Звонок" : "Текст"}</span></div>
      <div className="message-list" aria-live="polite" aria-atomic="false">{notice && <div className={`notice compact ${failedMessage ? "notice-error" : ""}`} role="status">{notice} {failedMessage && <button className="text-button" type="button" onClick={onRetryMessage} disabled={isReplying}>Повторить</button>}</div>}{coachNotice && <div className="notice compact notice-error" role="alert">{coachNotice}</div>}{messages.map((message) => { const audio = voiceRecordings.find((item) => item.messageId === message.id); return <article className={`message ${message.author} ${message.messageKind ?? "dialogue"}`} key={message.id}>{message.author !== "user" && <span className="message-author">{message.speakerLabel ?? (message.author === "system" ? "Система симуляции" : configuration.opponentRole)}</span>}{message.author === "user" && <span className="message-author">Вы</span>}<p>{message.text}</p>{audio && <div className="message-audio"><audio controls preload="none" src={audio.audioUrl}>Ваш браузер не поддерживает аудио.</audio><div><span>{Math.round(audio.durationMs / 1000)} сек · {audio.observations.speakingRateWpm} слов/мин · {audio.observations.pauseCount} пауз</span><button type="button" onClick={() => onDeleteVoice(audio.id)}>Удалить аудио</button></div></div>}<div className="message-meta"><time>{message.timestamp}</time>{message.messageKind === "event" && <span>ZOPA сохранена</span>}{message.author === "user" && lastParticipant?.id === message.id && !isReplying && sessionId && <button className="message-action" type="button" onClick={() => openRewrite(message)}>Переписать для тренировки</button>}</div></article>; })}{isReplying && <article className="message opponent loading-message" role="status"><span className="message-author">{simulation?.opponents[0]?.label ?? configuration.opponentRole}</span><span className="replying-label">Оппонент формулирует ответ…</span><span className="typing" aria-hidden="true"><i /><i /><i /></span></article>}</div>
      {hint && <aside className="coach-inline" aria-live="polite"><div><span className="coach-symbol" aria-hidden="true">?</span><div><span className="card-topline">Сократический намёк · {coachSkillLabel[hint.skillId]}</span><p>{hint.question}</p></div></div><footer><span>{hint.provider === "gemini" ? "Gemini" : "Резервный тренер"}{hint.cached ? " · из кэша" : ""}</span><span>{hint.budget.remainingCalls} AI-вызовов осталось</span><button className="text-button" type="button" onClick={() => setHint(null)}>Скрыть</button></footer></aside>}
      {rewriteTarget && <section className="rewrite-lab" aria-labelledby="rewrite-title"><header><div><span className="card-topline">Неофициальная учебная ветка</span><h2 id="rewrite-title">Что изменится, если сказать иначе?</h2></div><button className="text-button" type="button" onClick={() => { setRewriteTarget(null); setRewrite(null); }}>Закрыть</button></header><p className="immutability-note"><span aria-hidden="true">✓</span> Официальный диалог и балл не изменяются.</p><form onSubmit={analyzeRewrite}><label>Новая версия реплики<textarea rows={4} minLength={5} maxLength={4000} value={rewriteText} onChange={(event) => setRewriteText(event.target.value)} /></label><button className="button secondary" type="submit" disabled={rewriteLoading || rewriteText.trim().length < 5}>{rewriteLoading ? "Моделируем реакцию…" : "Показать возможное изменение"}</button></form>{rewrite && <div className="rewrite-result"><div className="possible-reply"><span>{configuration.opponentRole} мог бы ответить</span><blockquote>«{rewrite.possibleOpponentReply}»</blockquote></div><p>{rewrite.analysis}</p><div className="impact-list">{rewrite.impacts.map((item) => <article className={item.effect} key={`${item.skillId}-${item.title}`}><span>{item.effect === "improved" ? "+" : item.effect === "weakened" ? "−" : "="}</span><div><strong>{item.title}</strong><p>{item.explanation}</p></div></article>)}</div><button className="button primary" type="button" onClick={() => { onDraft(rewrite.revisedText); setRewriteTarget(null); setRewrite(null); }}>Использовать как следующую реплику</button><small>Это добавит новую реплику после редактирования; уже отправленная останется в протоколе.</small></div>}</section>}
      <details className="chat-advanced"><summary>Инструменты тренировки</summary>{simulation?.enabled && <aside className="hypothesis-lab"><header><div><span className="card-topline">Проверка гипотез</span><strong>Только по раскрытым фактам</strong></div><span>{simulation.disclosures.length} фактов</span></header><form onSubmit={testHypothesis}><input minLength={5} maxLength={500} value={hypothesisText} onChange={(event) => setHypothesisText(event.target.value)} placeholder="Например: для стороны критичен срок запуска" aria-label="Гипотеза об интересах стороны" /><button className="button ghost" type="submit" disabled={hypothesisLoading || hypothesisText.trim().length < 5}>{hypothesisLoading ? "Проверяем…" : "Проверить"}</button></form>{hypothesisNotice && <p className="field-error">{hypothesisNotice}</p>}{simulation.hypotheses.slice(-2).reverse().map((item) => <article className={`hypothesis-result ${item.status}`} key={item.id}><span>{{ confirmed: "Подтверждена", refuted: "Опровергнута", insufficient: "Недостаточно данных" }[item.status]}</span><p>{item.explanation}</p></article>)}</aside>}<div className="composer-tools"><button className="button coach-button" type="button" onClick={askHint} disabled={!sessionId || hintLoading || composerDisabled}>{hintLoading ? "Тренер думает…" : "Намёк"}</button><span>Тренер задаст вопрос, но не даст готовую сделку.</span></div></details>
      {preferredFormat === "call" ? <>
        {useBackupCall ? <LiveConversation sessionId={sessionId} messages={messages} disabled={isReplying || isFinishing || isTerminal} isTerminal={isTerminal} onTurn={onAutoTurn} onActiveChange={setLiveActive} /> : <CallConversation sessionId={sessionId} messages={messages} disabled={isReplying || isFinishing || isTerminal} isTerminal={isTerminal} onTurn={onAutoTurn} onActiveChange={setLiveActive} />}
        <details className="voice-alternatives"><summary>Если звонок работает нестабильно</summary><p>Можно использовать резервный голосовой режим в этой же тренировке.</p><button type="button" onClick={() => setUseBackupCall((current) => !current)}>{useBackupCall ? "Вернуться к звонку" : "Открыть резервный режим"}</button></details>
      </> : <>
        {composer}
        <details className="text-dictation"><summary>Продиктовать сообщение</summary><VoiceCapture messages={messages} draft={draft} disabled={composerDisabled} value={voiceDraft} notice={voiceNotice} onDraft={onDraft} onVoiceDraft={onVoiceDraft} /></details>
      </>}
      <footer className="chat-session-footer"><span>{isTerminal ? "Диалог завершён — отчёт готов к просмотру" : "Когда закончите, откройте разбор переговоров"}</span><button className="button primary" type="button" disabled={isReplying || isFinishing} onClick={onFinish}>{isFinishing ? "Готовим отчёт…" : isTerminal ? "Открыть отчёт" : "Завершить и получить отчёт"}</button></footer>
    </section>
  </section></main>;
}

function AdaptiveTrainerReport({ sessionId }: { sessionId: string }) {
  const [drill, setDrill] = useState<PersonalizedMiniDrill | null>(null);
  const [summary, setSummary] = useState<AdaptiveCoachSummary | null>(null);
  const [feedback, setFeedback] = useState<AdaptiveDrillFeedback | null>(null);
  const [answer, setAnswer] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "saving" | "error">("loading");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([getPersonalizedDrill(sessionId), getAdaptiveCoachSummary(sessionId)]).then(([drillResult, summaryResult]) => {
      if (!active) return;
      setDrill(drillResult.drill);
      setSummary(summaryResult.summary);
      const error = drillResult.error || summaryResult.error;
      setNotice(error || "");
      setStatus(drillResult.drill ? "ready" : "error");
    });
    return () => { active = false; };
  }, [sessionId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "saving" || answer.trim().length < 20) return;
    setStatus("saving"); setNotice("");
    const result = await completePersonalizedDrill(sessionId, answer.trim());
    if (!result.feedback) { setStatus("ready"); setNotice(result.error || "Не удалось проверить упражнение."); return; }
    setFeedback(result.feedback);
    const refreshed = await getAdaptiveCoachSummary(sessionId);
    if (refreshed.summary) setSummary(refreshed.summary);
    setStatus("ready");
  }

  if (status === "loading") return <section className="report-section adaptive-report"><div className="skeleton adaptive-skeleton" /></section>;
  if (!drill) return <section className="report-section adaptive-report"><div className="notice notice-error" role="alert">{notice || "Персональное упражнение временно недоступно."}</div></section>;
  const delta = summary?.skillDelta;
  return <section className="report-section adaptive-report" aria-labelledby="adaptive-report-title">
    <div className="section-heading"><div><span className="card-topline">Адаптивный AI-тренер</span><h2 id="adaptive-report-title">От ошибки — к новой реплике</h2><p>Упражнение построено по реальному диалогу, а не по абстрактному примеру.</p></div>{summary && <div className="coach-usage"><span>Навык</span><strong>{coachSkillLabel[summary.focusSkill]}</strong><small>{summary.hintCount} подсказок · {summary.rewriteCount} веток</small></div>}</div>
    {notice && <div className="notice notice-error" role="alert">{notice}</div>}
    <div className="adaptive-report-grid"><article className="personal-drill"><div className="drill-origin"><span>{drill.sourceTurn ? `Реплика ${drill.sourceTurn}` : "Диагностика отчёта"}</span>{drill.sourceQuote && <blockquote>«{drill.sourceQuote}»</blockquote>}</div><h3>{drill.title}</h3><p>{drill.prompt}</p><ol>{drill.instructions.map((item) => <li key={item}>{item}</li>)}</ol><details><summary>Чек-лист и опорная структура</summary><ul>{drill.successChecklist.map((item) => <li key={item}>{item}</li>)}</ul><blockquote>{drill.suggestedTemplate}</blockquote></details></article>
      <form className="adaptive-answer" onSubmit={submit}><label>Новая реплика<textarea rows={7} minLength={20} maxLength={2000} value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="Сформулируйте улучшенную реплику своими словами…" required /></label><button className="button primary" type="submit" disabled={status === "saving" || answer.trim().length < 20}>{status === "saving" ? "Проверяем…" : "Проверить по наблюдаемым признакам"}</button>{feedback && <div className={`drill-feedback ${feedback.passed ? "passed" : "retry"}`}><div><strong>{feedback.score}/100</strong><span>{feedback.passed ? "Навык проявился" : "Нужно усилить"}</span></div><p>{feedback.feedback}</p><ul>{feedback.checks.map((item) => <li className={item.met ? "met" : "missed"} key={item.title}>{item.met ? "✓" : "×"} {item.title}</li>)}</ul></div>}</form></div>
    <footer className="adaptive-integrity"><div><span aria-hidden="true">✓</span><p><strong>Официальный результат неизменен.</strong> Упражнение влияет только на подготовку следующей попытки.</p></div>{summary?.currentSkillScore !== null && summary?.currentSkillScore !== undefined && <div className="skill-measure"><span>Подтверждённый навык</span><strong>{summary.currentSkillScore}/100</strong>{delta !== null && delta !== undefined && <small className={delta > 0 ? "positive" : delta < 0 ? "negative" : ""}>{delta > 0 ? "+" : ""}{delta} к прошлой попытке</small>}</div>}</footer>
  </section>;
}

const peerStatusCopy: Record<PeerReviewSessionStatus["status"], { label: string; title: string; text: string }> = {
  waiting: { label: "В очереди", title: "Ожидает взаимной проверки", text: "Автоматический отчёт уже готов, а peer-review придёт отдельно и ничего не блокирует." },
  reviewed: { label: "Проверено", title: "Получена независимая рецензия", text: "Оценка рецензента опубликована отдельно от официального автоматического балла." },
  disputed: { label: "Сверяем", title: "Назначена вторая проверка", text: "Расхождение велико — система автоматически ищет второго независимого рецензента." },
  re_reviewing: { label: "Пересмотр", title: "Жалоба принята", text: "Другой рецензент проведёт повторную слепую проверку по той же рубрике." },
  resolved: { label: "Завершено", title: "Две проверки сопоставлены", text: "Пересмотр завершён. Официальный автоматический балл остался неизменным." },
};

function PeerReviewStatusPanel({ sessionId }: { sessionId: string }) {
  const { account, openAuth } = useContext(AccountNavigationContext);
  const [peerStatus, setPeerStatus] = useState<PeerReviewSessionStatus | null>(null);
  const [notice, setNotice] = useState("");
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);

  async function refresh() {
    const response = await getPeerReviewStatus(sessionId);
    setPeerStatus(response.status);
    setNotice(response.error ?? "");
  }

  useEffect(() => { void refresh(); }, [sessionId]);

  async function appeal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const first = peerStatus?.reviews[0];
    if (!first || reason.trim().length < 20) return;
    setSending(true);
    const response = await appealPeerReview(first.assignmentId, reason.trim());
    setSending(false);
    if (!response.accepted) { setNotice(response.error || "Не удалось отправить жалобу."); return; }
    setReason("");
    await refresh();
    setNotice(response.message || "Жалоба принята.");
  }

  if (!peerStatus) return <section className="peer-status-panel loading" aria-label="Статус взаимной проверки"><div className="skeleton peer-status-skeleton" />{notice && <p>{notice}</p>}</section>;
  const copy = peerStatusCopy[peerStatus.status];
  return <section className={`peer-status-panel ${peerStatus.status}`} aria-labelledby="peer-status-title">
    <div className="peer-status-head"><div><span className="card-topline">Полученная обратная связь</span><h2 id="peer-status-title">{copy.title}</h2><p>{copy.text}</p></div><span className="peer-status-badge">{copy.label}</span></div>
    <div className="peer-status-metrics"><div><span>Проверки</span><strong>{peerStatus.reviewsReceived}/{peerStatus.reviewsRequired}</strong></div><div><span>Сводная peer-оценка</span><strong>{peerStatus.consensusScore ?? "—"}</strong></div><div><span>SLA</span><strong>до {peerStatus.sla.targetHours} ч</strong></div></div>
    {peerStatus.reviews.length > 0 && <div className="received-review-list">{peerStatus.reviews.map((review) => <article key={review.assignmentId}><div><strong>{review.reviewerAlias}</strong><span>Раунд {review.reviewRound}{review.appealStatus === "pending" ? " · жалоба рассматривается" : review.appealStatus === "resolved" ? " · пересмотрено" : ""}</span></div><b>{review.peerScore === null ? "Ожидается" : `${review.peerScore}/100`}</b></article>)}</div>}
    <div className="peer-integrity-note"><span aria-hidden="true">✓</span><p><strong>Официальная автооценка не заменяется.</strong> {peerStatus.sla.fallback}</p></div>
    {peerStatus.canAppeal && account && <form className="peer-appeal" onSubmit={appeal}><label htmlFor="peer-appeal-reason">Не согласны с рецензией?<textarea id="peer-appeal-reason" rows={3} minLength={20} maxLength={1500} required value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Укажите конкретную реплику или критерий, который нужно пересмотреть…" /></label><button className="button secondary" type="submit" disabled={sending || reason.trim().length < 20}>{sending ? "Отправляем…" : "Запросить независимый пересмотр"}</button></form>}
    {peerStatus.canAppeal && !account && <button className="text-button" type="button" onClick={openAuth}>Войти, чтобы запросить пересмотр</button>}
    {notice && <div className={notice.includes("принята") ? "notice compact" : "notice notice-error compact"} role="status">{notice}</div>}
  </section>;
}

function Report({ sessionId, scenario, configuration, report, attemptNumber, comparison, historicalComparison, mode, notice, isRetrying, onCompare, onPeer, onRetry, onChange }: { sessionId: string | null; scenario: Scenario; configuration: SessionConfiguration; report: ReportData; attemptNumber: number; comparison: AttemptComparison | null; historicalComparison: HistoricalAttemptComparison | null; mode: "api" | "demo"; notice: string; isRetrying: boolean; onCompare: () => void; onPeer: () => void; onRetry: () => void; onChange: () => void }) {
  const evidence = (items: { turn: number; quote: string }[]) => items.length ? (
    <div className="evidence-list">
      {items.map((item, index) => <blockquote key={`${item.turn}-${index}`}><p>«{item.quote}»</p><cite>Реплика {item.turn}</cite></blockquote>)}
    </div>
  ) : null;

  return (
    <main className="app-shell">
      <Topbar step="report" />
      <section className="workspace report" id="main-content" aria-labelledby="report-title">
        <div className="eyebrow">Попытка {attemptNumber} завершена · {configuration.topic} · {mode === "api" ? "API" : "демо"}</div>
        <h1 id="report-title">Разбор переговоров</h1>
        {notice && <div className="notice" role="status">{notice}</div>}

        <div className="score-panel report-hero">
          <div className="score" aria-label={`Итоговый балл ${report.score} из 100`}><strong>{report.score}</strong><span>/100</span></div>
          <div><span className="outcome-kicker">{report.outcome.label}</span><h2>{report.label}</h2><p>{report.summary}</p></div>
        </div>

        <details className="report-disclosure"><summary>Исход и условия сделки</summary>
        {report.simulation && <section className="simulation-report" aria-labelledby="simulation-report-title"><div><span className="card-topline">Навык ≠ сложность среды</span><h2 id="simulation-report-title">Два независимых измерения</h2><p>{report.simulation.interpretation}</p></div><div className="simulation-report-metrics"><article><span>Навык участника</span><strong>{report.simulation.participantSkillScore}</strong><small>официальный балл / 100</small></article><article><span>Давление среды</span><strong>{report.simulation.environmentPressureScore}</strong><small>индекс сложности / 100</small></article></div><dl><div><dt>AI-участников</dt><dd>{report.simulation.aiParticipants}</dd></div><div><dt>Событий</dt><dd>{report.simulation.eventCount}</dd></div><div><dt>Просроченных решений</dt><dd>{report.simulation.timedOutDecisions}</dd></div><div><dt>Достигнутая фаза</dt><dd>{{ preparation: "Подготовка", opening: "Открытие", exploration: "Исследование", exchange: "Обмен", commitment: "Фиксация" }[report.simulation.phaseReached]}</dd></div></dl></section>}

        <div className="report-grid report-facts">
          <article className="panel">
            <h2>Сравнение с альтернативой</h2>
            <p>{report.outcome.meetsBatna === null ? "Недостаточно данных" : report.outcome.meetsBatna ? "Результат не хуже альтернативы (BATNA)." : "Результат хуже альтернативы (BATNA)."}</p>
            <p>{report.outcome.reservationRespected === null ? "Граница допустимого: данных недостаточно." : report.outcome.reservationRespected ? "Граница допустимого соблюдена." : "Граница допустимого нарушена."}</p>
          </article>
          <article className="panel quiet">
            <h2>Исход</h2><p>{report.outcome.description}</p>
            {report.outcome.acceptedTerms.length > 0 && <ul>{report.outcome.acceptedTerms.map((term, index) => <li key={`${index}-${term}`}>{term}</li>)}</ul>}
          </article>
        </div>
        </details>

        <section className="report-section" aria-labelledby="tasks-title">
          <div className="section-heading"><div><span className="card-topline">Сверка с брифингом</span><h2 id="tasks-title">Выполнение первоначальных задач</h2></div><span className="completion-count">{report.taskChecks.filter((item) => item.status === "met").length}/{report.taskChecks.length}</span></div>
          <div className="task-check-grid">{report.taskChecks.map((item) => <details className={`task-check ${item.status}`} key={item.id}><summary><span className="task-icon" aria-hidden="true">{item.status === "met" ? "✓" : "×"}</span><span className="task-check-title">{item.title}</span><span className="task-status">{item.status === "met" ? "Выполнено" : "Не выполнено"}</span></summary><p>{item.explanation}</p>{item.acceptedValue && <small>Итог: {item.acceptedValue}</small>}</details>)}</div>
        </section>

        <details className="report-disclosure"><summary>Подробная оценка</summary><section className="report-section" aria-labelledby="blocks-title">
          <h2 id="blocks-title">Баллы по блокам</h2>
          <div className="block-grid">{report.blocks.map((block) => (
            <article className="panel score-block" key={block.id}>
              <div className="block-heading"><h3>{block.title}</h3><strong>{block.score}<small>/{block.maxScore}</small></strong></div>
              <p>{block.explanation}</p>
              {block.criteria.map((criterion) => <div className="criterion" key={criterion.id}><div><strong>{criterion.title}</strong><span>{criterion.score}/{criterion.maxScore}</span></div><p>{criterion.explanation}</p>{evidence(criterion.evidence)}</div>)}
            </article>
          ))}</div>
        </section>

        <div className="report-grid">
          <article className="panel"><h2>Что получилось</h2>{report.strengths.length ? report.strengths.map((item) => <div className="finding" key={item.code}><h3>{item.title} <span>+{item.points}</span></h3><p>{item.explanation}</p>{evidence(item.evidence)}</div>) : <p>Положительные индикаторы пока не зафиксированы.</p>}</article>
          <article className="panel quiet"><h2>Штрафы</h2>{report.penalties.length ? report.penalties.map((item) => <div className="finding penalty" key={item.id}><h3>{item.title} <span>−{Math.abs(item.points * item.occurrences)}</span></h3><p>{item.explanation}</p>{evidence(item.evidence)}</div>) : <p>Штрафы не применялись.</p>}</article>
        </div>
        </details>

        {report.improvements.length > 0 && <section className="report-section report-improvement-section">
          <h2>Как улучшить следующую попытку</h2>
          <div className="improvement-grid">{report.improvements.slice(0, 1).map((item) => <article className="panel quiet report-improvement-card" key={item.priority}><span className="card-topline">Приём для следующей попытки</span><h3>{item.title}</h3><div className="report-improvement-flow">{item.originalQuote && <div className="report-improvement-quote"><span>Исходная реплика</span><p>«{item.originalQuote}»</p></div>}<div className="report-improvement-suggestion"><span>Попробуйте сказать</span><p>«{item.suggestedText}»</p></div></div><p className="report-improvement-rationale">{item.rationale}</p></article>)}</div>
          {report.improvements.length > 1 && <details className="report-disclosure"><summary>Ещё советы</summary><div className="improvement-grid">{report.improvements.slice(1).map((item) => <article className="panel quiet" key={item.priority}><h3>{item.title}</h3>{item.originalQuote && <p>«{item.originalQuote}»</p>}<p className="suggested">{item.suggestedText}</p><p>{item.rationale}</p></article>)}</div></details>}
        </section>}

        {report.score < 100 && report.coaching && <section className="report-section coaching-section" aria-labelledby="coaching-title">
          <div className="section-heading"><div><span className="card-topline">Персональная обратная связь</span><h2 id="coaching-title">Разбор ошибок {report.coaching.provider === "gemini" ? "Gemini" : "резервного оценщика"}</h2></div><span className={`analysis-badge ${report.coaching.fallback ? "fallback" : ""}`}>{report.coaching.provider === "gemini" ? "Gemini" : "Резервный режим"}</span></div>
          <p className="coaching-summary">{report.coaching.summary}</p>
          {report.coaching.fallback && <p className="coaching-note">Gemini не смог сформировать проверяемый разбор, поэтому показаны рекомендации детерминированного оценщика.</p>}
          <div className="coach-grid">{report.coaching.points.slice(0, 1).map((item, index) => <article className="coach-card" key={`${item.turn ?? "general"}-${index}`}><span className="card-topline">{item.turn ? `Реплика ${item.turn}` : "Главная зона роста"}</span>{item.quote && <blockquote>«{item.quote}»</blockquote>}<h3>Что изменить</h3><p>{item.problem}</p><p className="suggested">{item.suggestedText}</p></article>)}</div>
          {report.coaching.points.length > 1 && <details className="report-disclosure"><summary>Все ошибки и варианты реплик</summary><div className="coach-grid">{report.coaching.points.slice(1).map((item, index) => <article className="coach-card" key={`${item.turn ?? "general"}-${index}`}><span className="card-topline">{item.turn ? `Реплика ${item.turn}` : `Зона роста ${index + 2}`}</span>{item.quote && <blockquote>«{item.quote}»</blockquote>}<h3>Что помешало</h3><p>{item.problem}</p><h3>Как действовать лучше</h3><p>{item.betterApproach}</p><p className="suggested"><strong>Вариант реплики:</strong><br />{item.suggestedText}</p></article>)}</div></details>}
        </section>}

        <details className="report-disclosure"><summary>Траектория и методика</summary>
        {mode === "api" && sessionId && <AdaptiveTrainerReport sessionId={sessionId} />}

        <section className="report-section">
          <h2>Траектория переговоров</h2>
          <div className="trajectory" aria-label="График прогресса по ходам">{report.trajectory.map((point) => <div className="trajectory-point" key={point.turn}><span>Ход {point.turn}</span><i style={{ width: `${point.progress}%` }} /><small>прогресс {point.progress}</small></div>)}</div>
          <details className="trajectory-details"><summary>Открыть данные траектории</summary><table><caption className="sr-only">Траектория переговоров по ходам</caption><thead><tr><th>Ход</th><th>Доверие</th><th>Напряжение</th><th>Прогресс</th><th>Отношения</th></tr></thead><tbody>{report.trajectory.map((point) => <tr key={point.turn}><td>{point.turn}</td><td>{point.trust}</td><td>{point.tension}</td><td>{point.progress}</td><td>{point.relationship}</td></tr>)}</tbody></table></details>
        </section>

        <details className="methodology">
          <summary>Как рассчитана оценка</summary>
          <p><strong>{report.methodology.formula}</strong></p>
          <p>Баллы по блокам: {report.methodology.rawScore}; штрафы: {report.methodology.penaltyPoints}; рубрика {report.methodology.rubricVersion}.{report.methodology.scoreCap !== null && ` Итог ограничен ${report.methodology.scoreCap} баллами из-за результата хуже BATNA.`}</p>
          <p>{report.methodology.disclaimer}</p>
        </details>
        </details>
        <article className="panel next-step"><h2>Следующий шаг</h2><p>{report.nextStep}</p></article>
        {comparison && <article className="progress-invite">
          <div className="progress-delta"><span>{comparison.scoreDelta >= 0 ? "+" : ""}{comparison.scoreDelta}</span><small>баллов</small></div>
          <div><span className="card-topline">Попытка {comparison.previous.attemptNumber} → {comparison.current.attemptNumber}</span><h2>Сравнение прогресса готово</h2><p>{comparison.summary}</p></div>
          <button className="button primary" onClick={onCompare}>Открыть сравнение</button>
        </article>}
        {!comparison && historicalComparison && <article className="progress-invite historical-progress-invite">
          <div className="progress-delta"><span aria-hidden="true">2</span><small>отчёта</small></div>
          <div><span className="card-topline">Попытки {historicalComparison.previous.attemptNumber} и {historicalComparison.current.attemptNumber} · разные версии</span><h2>Оба отчёта доступны</h2><p>Покажем сохранённые баллы и версии оценки отдельно. Дельта между ними не рассчитывается.</p></div>
          <button className="button primary" onClick={onCompare}>Открыть историю</button>
        </article>}
        {mode === "api" && sessionId && <PeerReviewStatusPanel sessionId={sessionId} />}
        <article className="peer-invite">
          <div><span className="card-topline">Школа 21</span><h2>Проверьте чужой диалог</h2></div>
          <button className="button primary" onClick={onPeer}>Начать проверку <span aria-hidden="true">→</span></button>
        </article>
        <div className="action-row"><button className="button primary" disabled={isRetrying} onClick={onRetry}>{isRetrying ? "Создаём попытку…" : "Повторить и сравнить"}</button><button className="button secondary" onClick={onChange}>Другой сценарий</button></div>
      </section>
    </main>
  );
}

function HistoricalAttemptCard({ attempt }: { attempt: AttemptSnapshot }) {
  return <article>
    <span>Попытка {attempt.attemptNumber}</span>
    <strong>{attempt.score}</strong>
    <small>{attempt.outcomeLabel}</small>
    <dl className="historical-attempt-meta">
      <div><dt>Рубрика</dt><dd>{attempt.rubricVersion}</dd></div>
      <div><dt>Оценщик</dt><dd>{attempt.evaluatorVersion}</dd></div>
      <div><dt>Задачи</dt><dd>{attempt.tasksMet}/{attempt.tasksTotal}</dd></div>
      <div><dt>Реплики</dt><dd>{attempt.turns}</dd></div>
    </dl>
  </article>;
}

function HistoricalAttemptComparisonScreen({ comparison, onBack, onRetry, isRetrying }: { comparison: HistoricalAttemptComparison; onBack: () => void; onRetry: () => void; isRetrying: boolean }) {
  return <main className="app-shell"><Topbar step="comparison" /><section className="workspace attempt-comparison" id="main-content" aria-labelledby="historical-comparison-title">
    <button className="back-button" onClick={onBack}>← К разбору попытки {comparison.current.attemptNumber}</button>
    <div className="eyebrow">{comparison.scenarioTitle} · история попыток</div>
    <h1 id="historical-comparison-title">Сохранённые результаты</h1>
    <p className="lead">{comparison.summary}</p>
    <section className="attempt-hero historical-attempt-hero" aria-label="Баллы и версии двух попыток">
      <HistoricalAttemptCard attempt={comparison.previous} />
      <HistoricalAttemptCard attempt={comparison.current} />
    </section>
    <p className="historical-comparison-note">Каждый балл относится только к указанной версии рубрики и оценщика. Изменение балла между этими попытками не рассчитывается.</p>
    <div className="action-row"><button className="button primary" disabled={isRetrying} onClick={onRetry}>{isRetrying ? "Создаём попытку…" : `Начать попытку ${comparison.current.attemptNumber + 1}`}</button><button className="button secondary" onClick={onBack}>Вернуться к отчёту</button></div>
  </section></main>;
}

function AttemptComparisonScreen({ comparison, onBack, onRetry, isRetrying }: { comparison: AttemptComparison; onBack: () => void; onRetry: () => void; isRetrying: boolean }) {
  const deltaLabel = comparison.scoreDelta > 0 ? `+${comparison.scoreDelta}` : `${comparison.scoreDelta}`;
  const changeLabel = { improved: "Выполнено теперь", regressed: "Перестало выполняться", unchanged: "Без изменения" } as const;
  return <main className="app-shell"><Topbar step="comparison" /><section className="workspace attempt-comparison" id="main-content" aria-labelledby="comparison-title"><button className="back-button" onClick={onBack}>← К разбору попытки {comparison.current.attemptNumber}</button><div className="eyebrow">{comparison.scenarioTitle} · динамика навыка</div><h1 id="comparison-title">Сравнение попыток</h1><p className="lead">Система сопоставляет только одну версию сценария и ту же рубрику — дельта отражает изменение наблюдаемых действий, а не разные условия.</p>
    <section className="attempt-hero" aria-label={`Изменение итогового балла ${deltaLabel}`}><article><span>Попытка {comparison.previous.attemptNumber}</span><strong>{comparison.previous.score}</strong><small>{comparison.previous.outcomeLabel}</small></article><div className={`attempt-arrow ${comparison.scoreDelta > 0 ? "positive" : comparison.scoreDelta < 0 ? "negative" : "neutral"}`}><strong>{deltaLabel}</strong><span aria-hidden="true">→</span><small>{comparison.summary}</small></div><article><span>Попытка {comparison.current.attemptNumber}</span><strong>{comparison.current.score}</strong><small>{comparison.current.outcomeLabel}</small></article></section>
    <div className="attempt-facts"><article><span>Задачи</span><strong>{comparison.previous.tasksMet}/{comparison.previous.tasksTotal} → {comparison.current.tasksMet}/{comparison.current.tasksTotal}</strong></article><article><span>Реплики участника</span><strong>{comparison.previous.turns} → {comparison.current.turns}</strong></article><article><span>Исход</span><strong>{comparison.outcomeChanged ? "Изменился" : "Без изменения"}</strong></article></div>
    <section className="report-section" aria-labelledby="block-progress-title"><div className="section-heading"><div><span className="card-topline">Единая рубрика</span><h2 id="block-progress-title">Динамика по пяти блокам</h2></div></div><div className="attempt-block-list">{comparison.blockDeltas.map((block) => <article key={block.blockId}><div className="attempt-block-heading"><h3>{block.title}</h3><span className={block.delta > 0 ? "positive" : block.delta < 0 ? "negative" : "neutral"}>{block.delta > 0 ? `+${block.delta}` : block.delta}</span></div><div className="attempt-bars"><div><label>Было</label><i><b style={{ width: `${(block.previousScore / block.maxScore) * 100}%` }} /></i><strong>{block.previousScore}/{block.maxScore}</strong></div><div><label>Стало</label><i><b style={{ width: `${(block.currentScore / block.maxScore) * 100}%` }} /></i><strong>{block.currentScore}/{block.maxScore}</strong></div></div></article>)}</div></section>
    <section className="report-section" aria-labelledby="task-progress-title"><div className="section-heading"><div><span className="card-topline">Брифинг</span><h2 id="task-progress-title">Изменение выполнения задач</h2></div><span className="completion-count">{comparison.taskDeltas.filter((item) => item.currentStatus === "met").length}/{comparison.taskDeltas.length}</span></div><div className="attempt-task-list">{comparison.taskDeltas.map((task) => <article className={task.change} key={task.taskId}><span className="task-icon" aria-hidden="true">{task.currentStatus === "met" ? "✓" : "×"}</span><div><h3>{task.title}</h3><p>{changeLabel[task.change]}</p></div><strong>{task.previousStatus === "met" ? "Да" : "Нет"} → {task.currentStatus === "met" ? "Да" : "Нет"}</strong></article>)}</div></section>
    <div className="attempt-insight-grid"><article className="panel"><span className="card-topline">Закрепили</span><h2>Что улучшилось</h2>{comparison.improvedBlocks.length || comparison.resolvedFocus.length ? <ul>{comparison.improvedBlocks.map((item) => <li key={item}>{item}</li>)}{comparison.resolvedFocus.map((item) => <li key={item}>Закрыта зона: {item}</li>)}</ul> : <p>Положительной дельты пока нет — сравните поблочные изменения.</p>}</article><article className="panel quiet"><span className="card-topline">Фокус</span><h2>Следующая попытка</h2>{comparison.regressedBlocks.length || comparison.newFocus.length ? <ul>{comparison.regressedBlocks.map((item) => <li key={item}>{item}</li>)}{comparison.newFocus.map((item) => <li key={item}>{item}</li>)}</ul> : <p>{comparison.nextStep}</p>}</article></div>
    <article className="panel next-step"><h2>Рекомендация</h2><p>{comparison.nextStep}</p></article><div className="action-row"><button className="button primary" disabled={isRetrying} onClick={onRetry}>{isRetrying ? "Создаём попытку…" : `Начать попытку ${comparison.current.attemptNumber + 1}`}</button><button className="button secondary" onClick={onBack}>Вернуться к отчёту</button></div>
  </section></main>;
}

function PeerReviewScreen({ assignment, status, notice, onBack, onRetry, onSubmit }: { assignment: PeerReviewAssignment | null; status: "loading" | "ready" | "submitting" | "error"; notice: string; onBack: () => void; onRetry: () => void; onSubmit: (items: PeerReviewDraftItem[], overallComment: string) => void }) {
  const [items, setItems] = useState<PeerReviewDraftItem[]>([]);
  const [overallComment, setOverallComment] = useState("");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    if (!assignment) return;
    const firstMessageId = assignment.messages.find((message) => message.role === "participant")?.id ?? "";
    setItems(assignment.criteria.map((criterion) => ({ criterionId: criterion.id, score: criterion.maxScore, messageId: firstMessageId, comment: "", suggestedText: "" })));
    setOverallComment("");
    setValidationError("");
  }, [assignment]);

  function updateItem(criterionId: string, patch: Partial<PeerReviewDraftItem>) {
    setItems((current) => current.map((item) => item.criterionId === criterionId ? { ...item, ...patch } : item));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment) return;
    const missingComment = items.some((item) => item.comment.trim().length < 12);
    const missingSuggestion = items.some((item) => {
      const criterion = assignment.criteria.find((candidate) => candidate.id === item.criterionId);
      return criterion && item.score <= criterion.lowScoreThreshold && item.suggestedText.trim().length < 8;
    });
    if (missingComment) { setValidationError("Для каждого блока нужен содержательный комментарий не короче 12 символов."); return; }
    if (missingSuggestion) { setValidationError("Для низкой оценки добавьте улучшенную формулировку реплики."); return; }
    if (overallComment.trim().length < 12) { setValidationError("Добавьте общий вывод не короче 12 символов."); return; }
    setValidationError("");
    onSubmit(items, overallComment.trim());
  }

  const participantMessages = assignment?.messages.filter((message) => message.role === "participant") ?? [];
  const difficulty = { easy: "Поддерживающая", medium: "Сбалансированная", hard: "Требовательная" } as const;
  return <main className="app-shell"><Topbar step="peer" /><section className="workspace peer-workspace" id="main-content" aria-labelledby="peer-title"><button className="back-button" onClick={onBack}>← К своему разбору</button><div className="eyebrow">Модель «Школы 21» · двойная слепая проверка</div><h1 id="peer-title">{assignment?.assignmentKind === "calibration" ? "Калибровка рецензента" : "Рецензия чужого диалога"}</h1><p className="lead">Проверьте наблюдаемые действия участника по рубрике. Личности сторон и автоматический балл скрыты до отправки.</p>
    {assignment && <div className="peer-assignment-meta"><span>{assignment.assignmentKind === "calibration" ? "Калибровочное задание" : `Раунд ${assignment.reviewRound} из 2`}</span><span>{assignment.language.toUpperCase()}</span><span>{difficulty[assignment.difficulty]}</span><span>{assignment.reviewerAlias}</span></div>}
    <div className="privacy-banner" role="note"><span aria-hidden="true">◉</span><div><strong>Двойная анонимность и закрытая автооценка</strong><p>{assignment?.assignmentKind === "calibration" ? "Сначала оцените эталонный диалог — так система откалибрует вашу работу с рубрикой." : "Вы не знаете автора диалога, автор не знает вас. Предыдущие оценки откроются только после отправки."}</p></div></div>
    {status === "loading" && <div className="peer-loading"><div className="skeleton-card" /><div className="skeleton-card" /></div>}
    {status === "error" && <div className="empty-state"><h2>Не удалось выдать диалог</h2><p>{notice}</p><button className="button secondary" onClick={onRetry}>Повторить</button></div>}
    {assignment && <form onSubmit={submit}>
      <div className="peer-layout">
        <section className="peer-transcript" aria-labelledby="transcript-title"><div className="peer-sticky-heading"><span className="card-topline">{assignment.scenarioTitle}</span><h2 id="transcript-title">Диалог для проверки</h2><p>{assignment.instructions}</p><ul className="matching-reasons">{assignment.matchingReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul><small className="peer-sla">Очередь не блокирует обучение · цель выдачи до {assignment.sla.targetHours} ч</small></div><div className="review-message-list">{assignment.messages.map((message) => <article className={`review-message ${message.role}`} id={`peer-message-${message.id}`} key={message.id}><span>#{message.sequence} · {message.authorLabel}</span><p>{message.content}</p></article>)}</div></section>
        <section className="peer-rubric" aria-labelledby="rubric-title"><div className="peer-rubric-heading"><span className="card-topline">5 блоков · 100 баллов</span><h2 id="rubric-title">Ваш чек-лист</h2></div>{assignment.criteria.map((criterion, index) => {
          const item = items.find((candidate) => candidate.criterionId === criterion.id);
          if (!item) return null;
          const low = item.score <= criterion.lowScoreThreshold;
          return <fieldset className="review-criterion" key={criterion.id}><legend><span>{index + 1}</span>{criterion.title}<strong>{item.score}/{criterion.maxScore}</strong></legend><p>{criterion.description}</p><label className="score-label" htmlFor={`score-${criterion.id}`}>Оценка</label><div className="score-control"><input id={`score-${criterion.id}`} type="range" min={0} max={criterion.maxScore} value={item.score} onChange={(event) => updateItem(criterion.id, { score: Number(event.target.value) })} /><output>{item.score}</output></div><label htmlFor={`message-${criterion.id}`}>Реплика участника — доказательство</label><select id={`message-${criterion.id}`} value={item.messageId} onChange={(event) => updateItem(criterion.id, { messageId: event.target.value })}>{participantMessages.map((message) => <option value={message.id} key={message.id}>#{message.sequence} · {message.authorLabel}: {message.content.slice(0, 64)}</option>)}</select><label htmlFor={`comment-${criterion.id}`}>Почему вы поставили этот балл</label><textarea id={`comment-${criterion.id}`} rows={3} value={item.comment} onChange={(event) => updateItem(criterion.id, { comment: event.target.value })} placeholder="Свяжите оценку с выбранной репликой…" />{low && <div className="low-score-field"><label htmlFor={`suggestion-${criterion.id}`}>Как участнику стоило сказать</label><textarea id={`suggestion-${criterion.id}`} rows={3} value={item.suggestedText} onChange={(event) => updateItem(criterion.id, { suggestedText: event.target.value })} placeholder="Предложите улучшенную формулировку…" /><small>Обязательно для оценки {criterion.lowScoreThreshold} и ниже.</small></div>}</fieldset>;
        })}<div className="overall-review"><label htmlFor="overall-comment">Общий вывод</label><textarea id="overall-comment" rows={4} value={overallComment} onChange={(event) => setOverallComment(event.target.value)} placeholder="Назовите главный сильный ход и основную зону роста…" /></div>{(validationError || notice) && <div className="notice notice-error" role="alert">{validationError || notice}</div>}<button className="button primary peer-submit" type="submit" disabled={status === "submitting"}>{status === "submitting" ? "Сверяем оценки…" : "Отправить рецензию и открыть сверку"}</button></section>
      </div>
    </form>}
  </section></main>;
}

function PeerReviewResultScreen({ result, onBack, onNext }: { result: PeerReviewResult; onBack: () => void; onNext: () => void }) {
  const signed = result.difference > 0 ? `+${result.difference}` : `${result.difference}`;
  const statusCopy = {
    accepted: { label: "Принято", text: "Рецензия согласуется с автоматической рубрикой." },
    second_review_required: { label: "Нужна 2-я проверка", text: "Расхождение существенно — назначена независимая повторная проверка." },
    resolved: { label: "Спор разрешён", text: "Вторая независимая проверка завершена." },
    calibrated: { label: "Калибровка пройдена", text: "Теперь вам доступны реальные диалоги участников." },
  }[result.reviewStatus];
  const reputationMetrics = [
    { label: "Точность", value: result.reputation.accuracy },
    { label: "Доказательность", value: result.reputation.evidenceQuality },
    { label: "Полезность", value: result.reputation.helpfulness },
  ];
  return <main className="app-shell"><Topbar step="peer_result" /><section className="workspace peer-result" id="main-content" aria-labelledby="peer-result-title"><div className="eyebrow">{result.assignmentKind === "calibration" ? "Калибровка завершена" : `Рецензия отправлена · раунд ${result.reviewRound}`}</div><h1 id="peer-result-title">Сверка с рубрикой</h1><p className="lead">Теперь автоматическая оценка открыта. Сравните расхождения — это тренирует не только переговоры, но и качество обратной связи.</p><div className="review-resolution"><div><span>{statusCopy.label}</span><strong>{result.reviewsReceived}/{result.reviewsRequired} проверок</strong></div><p>{statusCopy.text} Очередь не блокирует дальнейшее обучение.</p></div><div className="comparison-hero"><div><span>Ваша оценка</span><strong>{result.peerScore}</strong></div><div className="comparison-delta"><span>Расхождение</span><strong>{signed}</strong><small>по модулю {result.absoluteDifference}</small></div><div><span>Автооценка</span><strong>{result.automaticScore}</strong></div></div><div className="official-note"><span aria-hidden="true">✓</span><div><strong>Официальный балл не изменён</strong><p>Peer-review публикуется как отдельная обратная связь и никогда не заменяет результат системы.</p></div></div><section className="report-section"><h2>Расхождения по блокам</h2><div className="comparison-list">{result.comparison.map((item) => <article key={item.criterionId}><div><h3>{item.title}</h3><span className={Math.abs(item.difference) <= 2 ? "aligned" : "diverged"}>{item.difference > 0 ? `+${item.difference}` : item.difference}</span></div><div className="comparison-bars"><label>Вы <i style={{ width: `${(item.peerScore / item.maxScore) * 100}%` }} /></label><strong>{item.peerScore}/{item.maxScore}</strong><label>Система <i style={{ width: `${(item.automaticScore / item.maxScore) * 100}%` }} /></label><strong>{item.automaticScore}/{item.maxScore}</strong></div></article>)}</div></section><article className="reputation-card"><div className="reputation-score"><strong>{result.reputation.points}</strong><span>/100</span></div><div className="reputation-content"><span className="card-topline">Репутация рецензента · {result.reputation.reviewsCompleted} проверок</span><h2>{result.reputation.label}</h2><p>{result.reputation.explanation}</p><div className="reputation-metrics">{reputationMetrics.map((metric) => <div key={metric.label}><span>{metric.label}</span><i><b style={{ width: `${metric.value}%` }} /></i><strong>{metric.value}</strong></div>)}</div><small>{result.feedback}</small></div></article><div className="action-row"><button className="button primary" onClick={onNext}>{result.assignmentKind === "calibration" ? "Перейти к реальному диалогу" : "Проверить ещё диалог"}</button><button className="button secondary" onClick={onBack}>Вернуться к своему разбору</button></div></section></main>;
}

function ScenarioSkeleton() { return <div className="scenario-grid" aria-label="Загрузка сценариев"><div className="skeleton-card" /><div className="skeleton-card" /></div>; }
function EmptyState({ onRetry }: { onRetry: () => void }) { return <div className="empty-state"><h2>Сценарии пока недоступны</h2><p>Проверьте подключение к серверу или повторите попытку.</p><button className="button secondary" onClick={onRetry}>Повторить загрузку</button></div>; }

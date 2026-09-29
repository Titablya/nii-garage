import { demoReport, demoScenarios } from "./demo-data";
import type { AccountHistory, AccountProfile, AdaptiveCoachSummary, AdaptiveDrillFeedback, AttemptComparison, AttemptComparisonResult, AuthResult, ChatMessage, CoachBudget, CoachHint, CoachRewrite, GenerationMetadata, HistoricalAttemptComparison, HypothesisResult, LearningDashboard, LearningDashboardResult, MessageResult, MotivationDashboard, MotivationDashboardResult, PeerReviewAssignment, PeerReviewAssignmentResult, PeerReviewDraftItem, PeerReviewResult, PeerReviewSessionStatus, PeerReviewSubmitResult, PersonalizedMiniDrill, PrebriefWorksheet, PrebriefWorksheetInput, Report, ReportResult, Scenario, ScenarioDraft, ScenarioDraftInput, ScenarioTextSuggestion, SessionConfiguration, SessionRestoreResult, SessionStartResult, SimulationSnapshot, VoiceDraft, VoiceRecording } from "./types";

export type ScenariosResult = { scenarios: Scenario[]; source: "api" | "demo"; error?: string };
export type ScenarioResult = { scenario: Scenario | null; error?: string };

type ApiScenario = {
  id: string;
  title: string;
  summary: string;
  participant_role: string;
  opponent_role: string;
  objective: string;
  context: string;
  estimated_minutes: number;
  configurable?: boolean;
  tone?: string;
  difficulty?: string;
  max_turns?: number;
  methods?: string[];
  tasks?: Array<{ id: string; title: string; description: string }>;
  industry?: string;
  negotiation_type?: string;
  theme?: string;
  role_tags?: string[];
  source?: "curated" | "custom";
  revision?: number;
};

type ApiMessageExchange = {
  participant_message: ApiMessage;
  opponent_message: ApiMessage;
  opponent_messages?: ApiMessage[];
  simulation_messages?: ApiMessage[];
  session?: { status?: string; simulation?: ApiSimulation };
  generation?: Partial<GenerationMetadata>;
};

type ApiMessage = { id: string; role: string; content: string; created_at: string; speaker_id?: string | null; speaker_label?: string | null; message_kind?: "dialogue" | "event" | "timeout" };
type ApiSimulation = {
  enabled: boolean; seed: number; mode: SimulationSnapshot["mode"]; phase: SimulationSnapshot["phase"];
  decision_time_seconds: number; deadline_at?: string | null; server_time: string; timed_out_decisions: number; pressure_score: number;
  events: Array<{ id: string; kind: "budget" | "deadline" | "authority" | "resource"; title: string; description: string; trigger_turn: number; severity: number; zopa_preserved: true }>;
  disclosures: Array<{ id: string; text: string; source_turn: number }>;
  hypotheses: Array<{ id: string; text: string; status: "confirmed" | "refuted" | "insufficient"; explanation: string; evidence_fact_id?: string | null; checked_at: string }>;
  opponents: Array<{ id: string; label: string; role: string; strategy: "analytical" | "collaborative" | "competitive" | "cautious" }>;
};

type ApiSession = {
  id: string;
  scenario_id: string;
  attempt_number: number;
  status: "active" | "completed";
  configuration: {
    topic: string;
    context: string;
    participant_role: string;
    opponent_role: string;
    objective: string;
    difficulty: SessionConfiguration["difficulty"];
    tone: SessionConfiguration["tone"];
    max_turns: number;
    simulation?: { enabled: boolean; mode: SessionConfiguration["simulation"]["mode"]; opponent_strategy: SessionConfiguration["simulation"]["opponentStrategy"]; ai_participants: 1 | 2 | 3; event_intensity: 0 | 1 | 2; decision_time_seconds: number; seed?: number | null };
  };
  messages: ApiMessage[];
  simulation: ApiSimulation;
};

type ApiReport = {
  session_id: string; scenario_id: string; scenario_version_id: string; rubric_version: string; evaluator_version: string; status: string; score: number; level: string; label: string; summary: string;
  outcome: { kind: string; label: string; description: string; participant_utility?: number | null; batna_utility?: number | null; meets_batna?: boolean | null; reservation_respected?: boolean | null; accepted_terms?: unknown[] };
  blocks: Array<{ id: string; title: string; score: number; max_score: number; explanation: string; criteria: Array<{ id: string; title: string; score: number; max_score: number; explanation: string; evidence: Array<{ message_id: string; turn: number; quote: string }> }> }>;
  penalties: Array<{ id: string; title: string; points: number; occurrences: number; explanation: string; evidence: Array<{ message_id: string; turn: number; quote: string }> }>;
  strengths: Array<{ code: string; title: string; explanation: string; points: number; evidence: Array<{ message_id: string; turn: number; quote: string }> }>;
  improvements: Array<{ priority: number; title: string; original_quote: string | null; suggested_text: string; rationale: string; indicator_id: string }>;
  task_checks?: Array<{ id: string; title: string; status: "met" | "not_met"; explanation: string; accepted_value?: string | null }>;
  coaching?: { provider: "gemini" | "deterministic"; model?: string | null; fallback: boolean; reason?: string | null; summary: string; points?: Array<{ turn?: number | null; quote?: string | null; problem: string; better_approach: string; suggested_text: string }> } | null;
  trajectory: Array<{ turn: number; trust: number; tension: number; progress: number; relationship: number }>;
  methodology: { rubric_version: string; formula: string; raw_score: number; penalty_points: number; score_cap?: number | null; disclaimer: string };
  simulation?: { participant_skill_score: number; environment_pressure_score: number; event_count: number; timed_out_decisions: number; ai_participants: number; phase_reached: SimulationSnapshot["phase"]; mode: SimulationSnapshot["mode"]; interpretation: string } | null;
  next_step: string;
};

function responseServerTime(response: Response, fallback: string): string {
  const header = response.headers.get("date");
  if (!header) return fallback;
  const parsed = new Date(header);
  return Number.isNaN(parsed.getTime()) ? fallback : parsed.toISOString();
}

function normalizeSimulation(value: ApiSimulation, observedServerTime?: string): SimulationSnapshot {
  return {
    enabled: value.enabled, seed: value.seed, mode: value.mode, phase: value.phase,
    decisionTimeSeconds: value.decision_time_seconds, deadlineAt: value.deadline_at ?? null,
    serverTime: observedServerTime ?? value.server_time, timedOutDecisions: value.timed_out_decisions, pressureScore: value.pressure_score,
    events: value.events.map((item) => ({ id: item.id, kind: item.kind, title: item.title, description: item.description, triggerTurn: item.trigger_turn, severity: item.severity, zopaPreserved: item.zopa_preserved })),
    disclosures: value.disclosures.map((item) => ({ id: item.id, text: item.text, sourceTurn: item.source_turn })),
    hypotheses: value.hypotheses.map((item) => ({ id: item.id, text: item.text, status: item.status, explanation: item.explanation, evidenceFactId: item.evidence_fact_id ?? null, checkedAt: item.checked_at })),
    opponents: value.opponents,
  };
}

function normalizeApiMessage(message: ApiMessage): ChatMessage {
  return { id: message.id, author: message.role === "participant" ? "user" : message.role === "opponent" ? "opponent" : "system", text: message.content, timestamp: restoreTimestamp(message.created_at), speakerId: message.speaker_id ?? null, speakerLabel: message.speaker_label ?? null, messageKind: message.message_kind ?? "dialogue" };
}

const fallbackReply = "Понимаю вашу задачу. Если для вас критичен срок, давайте посмотрим, какие условия позволят нам сдвинуть график без риска для поставки.";
const fallbackGeneration: GenerationMetadata = { provider: "fallback", model: null, fallback: true, reason: "Метаданные генерации недоступны" };

function normalizeGeneration(generation?: Partial<GenerationMetadata>): GenerationMetadata {
  if (!generation) return fallbackGeneration;
  return { provider: generation.provider || "fallback", model: generation.model ?? null, fallback: generation.fallback ?? true, reason: generation.reason ?? null };
}

function normalizeAcceptedTerms(value: unknown[] | undefined): string[] {
  return (value ?? []).filter((term): term is string => typeof term === "string" && term.trim().length > 0);
}

function normalizeScenarioTasks(value: ApiScenario["tasks"], fallback: Scenario["tasks"]): Scenario["tasks"] {
  if (!Array.isArray(value) || value.length === 0) return fallback;
  const tasks = value.filter((item) => item && typeof item.id === "string" && typeof item.title === "string" && typeof item.description === "string");
  return tasks.length ? tasks : fallback;
}

function apiBaseUrl(): string {
  // An empty base keeps browser requests on the current origin. Next.js then
  // proxies /api/v1 to the private backend, so public tunnel visitors never
  // need direct access to port 8000.
  return process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "";
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.split("; ").find((item) => item.startsWith("arena_csrf="));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : "";
}

function mutationHeaders(): Record<string, string> {
  const token = csrfToken();
  return token ? { "Content-Type": "application/json", "X-CSRF-Token": token } : { "Content-Type": "application/json" };
}

async function apiError(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null) as { detail?: string | Array<{ msg?: string }> } | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) return payload.detail[0]?.msg || `Сервер вернул ${response.status}`;
  return `Сервер вернул ${response.status}`;
}

function normalizeScenario(item: ApiScenario): Scenario {
  const local = demoScenarios.find((scenario) => scenario.id === item.id);
  const difficulty: SessionConfiguration["difficulty"] = item.difficulty === "beginner" || item.difficulty === "easy" ? "easy" : item.difficulty === "advanced" || item.difficulty === "hard" ? "hard" : "medium";
  const tone: SessionConfiguration["tone"] = item.tone === "cooperative" ? "cooperative" : item.tone === "assertive" || item.tone === "tense" || item.tone === "firm" ? "firm" : "businesslike";
  const configurationMetadata = {
    configurable: item.configurable ?? true,
    difficulty,
    tone,
    maxTurns: item.max_turns ?? local?.maxTurns ?? 12,
    industry: item.industry ?? "Общее",
    negotiationType: item.negotiation_type ?? "procurement",
    theme: item.theme ?? "Деловые переговоры",
    roleTags: item.role_tags ?? [item.participant_role, item.opponent_role],
    methods: item.methods ?? [],
    source: item.source ?? "curated",
    revision: item.revision ?? 1,
  };
  if (local) {
    return {
      ...local,
      ...configurationMetadata,
      title: item.title,
      description: item.summary,
      role: item.participant_role,
      opponent: item.opponent_role,
      objective: item.objective,
      context: item.context,
      duration: `${item.estimated_minutes} минут`,
      tasks: normalizeScenarioTasks(item.tasks, local.tasks),
    };
  }
  return {
    ...configurationMetadata,
    id: item.id,
    title: item.title,
    subtitle: `${item.theme ?? "Деловые переговоры"} · ${item.industry ?? "Общее"}`,
    description: item.summary,
    role: item.participant_role,
    opponent: item.opponent_role,
    duration: `${item.estimated_minutes} минут`,
    skills: ["интересы сторон", "деловой тон", "фиксация результата"],
    objective: item.objective,
    context: item.context || item.summary,
    tasks: normalizeScenarioTasks(item.tasks, [{ id: "outcome.agreement", title: item.objective, description: "Зафиксируйте измеримый итог переговоров." }]),
  };
}

export async function getScenarios(): Promise<ScenariosResult> {
  const baseUrl = apiBaseUrl();
  try {
    const response = await fetch(`${baseUrl}/api/v1/scenarios`, { signal: AbortSignal.timeout(3500), credentials: "include" });
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    const payload = (await response.json()) as ApiScenario[] | { scenarios: ApiScenario[] };
    const scenarios = Array.isArray(payload) ? payload : payload.scenarios;
    if (!Array.isArray(scenarios) || scenarios.length === 0) throw new Error("Сервер не вернул сценарии");
    return { scenarios: scenarios.map(normalizeScenario), source: "api" };
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : "Неизвестная ошибка";
    return { scenarios: demoScenarios, source: "demo", error: message };
  }
}

export async function getScenarioCatalog(): Promise<ScenariosResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/scenario-catalog`, {
      signal: AbortSignal.timeout(7000),
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await apiError(response));
    const payload = await response.json() as ApiScenario[];
    return { scenarios: payload.map(normalizeScenario), source: "api" };
  } catch (cause) {
    return { scenarios: [], source: "demo", error: cause instanceof Error ? cause.message : "Каталог недоступен" };
  }
}

type ApiScenarioDraft = {
  id: string;
  series_id: string;
  version: number;
  scenario: ApiScenario;
  validation: {
    valid: true;
    checked_issues: number;
    overlapping_issues: number;
    no_overlap_issues: number;
    alternative_integrity: true;
    reservation_integrity: true;
    hidden_fields_exposed: false;
  };
  created_at: string;
};

function normalizeScenarioDraft(payload: ApiScenarioDraft): ScenarioDraft {
  return {
    id: payload.id,
    seriesId: payload.series_id,
    version: payload.version,
    scenario: normalizeScenario(payload.scenario),
    validation: {
      valid: payload.validation.valid,
      checkedIssues: payload.validation.checked_issues,
      overlappingIssues: payload.validation.overlapping_issues,
      noOverlapIssues: payload.validation.no_overlap_issues,
      alternativeIntegrity: payload.validation.alternative_integrity,
      reservationIntegrity: payload.validation.reservation_integrity,
      hiddenFieldsExposed: payload.validation.hidden_fields_exposed,
    },
    createdAt: payload.created_at,
  };
}

function draftPayload(input: ScenarioDraftInput) {
  return {
    ...(input.seriesId ? { series_id: input.seriesId } : {}),
    template_id: input.templateId,
    title: input.title,
    situation: input.situation,
    participant_role: input.participantRole,
    opponent_role: input.opponentRole,
    objective: input.objective,
    industry: input.industry,
    theme: input.theme,
    difficulty: input.difficulty,
    tone: input.tone,
    estimated_minutes: input.estimatedMinutes,
    max_turns: input.maxTurns,
    stakes_level: input.stakesLevel,
  };
}

export async function getScenarioDrafts(): Promise<{ drafts: ScenarioDraft[]; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/me/scenario-drafts`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return { drafts: [], error: await apiError(response) };
    const payload = await response.json() as { drafts: ApiScenarioDraft[] };
    return { drafts: payload.drafts.map(normalizeScenarioDraft) };
  } catch (cause) {
    return { drafts: [], error: cause instanceof Error ? cause.message : "Не удалось загрузить черновики" };
  }
}

export async function saveScenarioDraft(input: ScenarioDraftInput): Promise<{ draft: ScenarioDraft | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/me/scenario-drafts`, {
      method: "POST",
      headers: mutationHeaders(),
      credentials: "include",
      body: JSON.stringify(draftPayload(input)),
    });
    if (!response.ok) return { draft: null, error: await apiError(response) };
    return { draft: normalizeScenarioDraft(await response.json() as ApiScenarioDraft) };
  } catch (cause) {
    return { draft: null, error: cause instanceof Error ? cause.message : "Не удалось сохранить черновик" };
  }
}

export async function suggestScenarioText(input: Pick<ScenarioDraftInput, "title" | "situation" | "participantRole" | "opponentRole" | "objective">): Promise<{ suggestion: ScenarioTextSuggestion | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/me/scenario-drafts/suggest`, {
      method: "POST",
      headers: mutationHeaders(),
      credentials: "include",
      body: JSON.stringify({ title: input.title, situation: input.situation, participant_role: input.participantRole, opponent_role: input.opponentRole, objective: input.objective }),
    });
    if (!response.ok) return { suggestion: null, error: await apiError(response) };
    return { suggestion: await response.json() as ScenarioTextSuggestion };
  } catch (cause) {
    return { suggestion: null, error: cause instanceof Error ? cause.message : "Помощник временно недоступен" };
  }
}

async function fetchScenario(path: string): Promise<ScenarioResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
      credentials: "include",
    });
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    return { scenario: normalizeScenario((await response.json()) as ApiScenario) };
  } catch (cause) {
    return { scenario: null, error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

export function getScenario(scenarioId: string): Promise<ScenarioResult> {
  return fetchScenario(`/api/v1/scenarios/${encodeURIComponent(scenarioId)}`);
}

export function getRandomScenario(excludeId?: string): Promise<ScenarioResult> {
  const query = excludeId ? `?exclude_id=${encodeURIComponent(excludeId)}` : "";
  return fetchScenario(`/api/v1/scenarios/random${query}`);
}

export async function createSession(scenarioId: string, configuration?: SessionConfiguration): Promise<SessionStartResult> {
  const baseUrl = apiBaseUrl();
  try {
    const response = await fetch(`${baseUrl}/api/v1/sessions`, {
      method: "POST",
      headers: mutationHeaders(),
      credentials: "include",
      body: JSON.stringify({ scenario_id: scenarioId, ...(configuration ? { configuration: { topic: configuration.topic, context: configuration.context, participant_role: configuration.participantRole, opponent_role: configuration.opponentRole, objective: configuration.objective, difficulty: configuration.difficulty, tone: configuration.tone, max_turns: configuration.maxTurns, simulation: { enabled: configuration.simulation.enabled, mode: configuration.simulation.mode, opponent_strategy: configuration.simulation.opponentStrategy, ai_participants: configuration.simulation.aiParticipants, event_intensity: configuration.simulation.eventIntensity, decision_time_seconds: configuration.simulation.decisionTimeSeconds, seed: configuration.simulation.seed } } } : {}) }),
    });
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    const payload = (await response.json()) as { id: string; attempt_number?: number; simulation: ApiSimulation };
    return { sessionId: payload.id, attemptNumber: payload.attempt_number ?? 1, source: "api", simulation: normalizeSimulation(payload.simulation, responseServerTime(response, payload.simulation.server_time)) };
  } catch (cause) {
    return { sessionId: null, source: "demo", error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

function restoreTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "ранее";
  return parsed.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function restoreMessages(payload: ApiSession): ChatMessage[] {
  return payload.messages.map(normalizeApiMessage);
}

export async function getSession(sessionId: string): Promise<SessionRestoreResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
      credentials: "include",
    });
    if (response.status === 404) throw new Error("Сессия больше не доступна");
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    const payload = (await response.json()) as ApiSession;
    return {
      session: {
        sessionId: payload.id,
        scenarioId: payload.scenario_id,
        attemptNumber: payload.attempt_number,
        status: payload.status,
        configuration: {
          topic: payload.configuration.topic,
          context: payload.configuration.context,
          participantRole: payload.configuration.participant_role,
          opponentRole: payload.configuration.opponent_role,
          objective: payload.configuration.objective,
          difficulty: payload.configuration.difficulty,
          tone: payload.configuration.tone,
          maxTurns: payload.configuration.max_turns,
          simulation: payload.configuration.simulation ? {
            enabled: payload.configuration.simulation.enabled,
            mode: payload.configuration.simulation.mode,
            opponentStrategy: payload.configuration.simulation.opponent_strategy,
            aiParticipants: payload.configuration.simulation.ai_participants,
            eventIntensity: payload.configuration.simulation.event_intensity,
            decisionTimeSeconds: payload.configuration.simulation.decision_time_seconds,
            seed: payload.configuration.simulation.seed ?? null,
          } : { enabled: true, mode: "meeting", opponentStrategy: "analytical", aiParticipants: 1, eventIntensity: 1, decisionTimeSeconds: 90, seed: null },
        },
        messages: restoreMessages(payload),
        simulation: normalizeSimulation(payload.simulation, responseServerTime(response, payload.simulation.server_time)),
      },
    };
  } catch (cause) {
    return { session: null, error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

export async function sendSessionMessage(sessionId: string | null, content: string): Promise<MessageResult> {
  const baseUrl = apiBaseUrl();
  if (!sessionId) return { reply: fallbackReply, source: "demo", generation: fallbackGeneration, sessionStatus: "active" };
  try {
    const response = await fetch(`${baseUrl}/api/v1/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: mutationHeaders(),
      credentials: "include",
      body: JSON.stringify({ content }),
    });
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    const payload = (await response.json()) as ApiMessageExchange;
    const replies = [...(payload.simulation_messages ?? []), ...(payload.opponent_messages ?? [payload.opponent_message])].map(normalizeApiMessage);
    return { reply: payload.opponent_message.content, replies, participantMessageId: payload.participant_message.id, source: "api", generation: normalizeGeneration(payload.generation), sessionStatus: payload.session?.status, simulation: payload.session?.simulation ? normalizeSimulation(payload.session.simulation, responseServerTime(response, payload.session.simulation.server_time)) : undefined };
  } catch (cause) {
    return { source: "api", generation: fallbackGeneration, error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

export async function getOpponentAudio(sessionId: string, messageId: string): Promise<{ audio: Blob | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/opponent-audio`, {
      method: "POST",
      headers: mutationHeaders(),
      credentials: "include",
      cache: "no-store",
      body: JSON.stringify({ message_id: messageId }),
    });
    if (!response.ok) return { audio: null, error: await apiError(response) };
    const audio = await response.blob();
    if (!audio.size || !audio.type.startsWith("audio/")) return { audio: null, error: "Аудиоответ недоступен" };
    return { audio };
  } catch (cause) {
    return { audio: null, error: cause instanceof Error ? cause.message : "Не удалось получить голос оппонента" };
  }
}

async function openAudioStream(
  sessionId: string, route: "opponent-audio-stream" | "opening-audio-stream", signal: AbortSignal, messageId?: string,
): Promise<{ response: Response | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/${route}`, {
      method: "POST",
      headers: mutationHeaders(),
      credentials: "include",
      cache: "no-store",
      body: messageId ? JSON.stringify({ message_id: messageId }) : undefined,
      signal,
    });
    if (!response.ok || !response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("audio/l16")) {
      return { response: null, error: response.ok ? "Потоковый голос недоступен" : await apiError(response) };
    }
    return { response };
  } catch (cause) {
    return { response: null, error: cause instanceof Error ? cause.message : "Не удалось подключить голос" };
  }
}

export function openOpponentAudioStream(sessionId: string, messageId: string, signal: AbortSignal) {
  return openAudioStream(sessionId, "opponent-audio-stream", signal, messageId);
}

export function openOpeningAudioStream(sessionId: string, signal: AbortSignal) {
  return openAudioStream(sessionId, "opening-audio-stream", signal);
}

type ApiVoiceRecording = {
  id: string; session_id: string; message_id: string; mime_type: string; byte_size: number;
  duration_ms: number; transcript: string; retention_policy: "24_hours" | "30_days";
  observations: { pause_count: number; longest_pause_ms: number; speaking_rate_wpm: number; interruption_count: number };
  audio_url: string; expires_at: string; created_at: string;
};

function normalizeVoiceRecording(value: ApiVoiceRecording): VoiceRecording {
  return {
    id: value.id, sessionId: value.session_id, messageId: value.message_id, mimeType: value.mime_type,
    byteSize: value.byte_size, durationMs: value.duration_ms, transcript: value.transcript,
    retentionPolicy: value.retention_policy,
    observations: { pauseCount: value.observations.pause_count, longestPauseMs: value.observations.longest_pause_ms, speakingRateWpm: value.observations.speaking_rate_wpm, interruptionCount: value.observations.interruption_count },
    audioUrl: value.audio_url, expiresAt: value.expires_at, createdAt: value.created_at,
  };
}

async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

export async function uploadVoiceRecording(sessionId: string, messageId: string, transcript: string, draft: VoiceDraft): Promise<{ recording: VoiceRecording | null; error?: string }> {
  if (draft.retentionPolicy === "do_not_store") return { recording: null };
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/voice-recordings`, {
      method: "POST", headers: mutationHeaders(), credentials: "include",
      body: JSON.stringify({
        message_id: messageId, audio_base64: await blobToBase64(draft.blob), mime_type: draft.mimeType,
        duration_ms: draft.durationMs, transcript, retention_policy: draft.retentionPolicy,
        consent: true, consent_version: "voice-v1",
        observations: { pause_count: draft.observations.pauseCount, longest_pause_ms: draft.observations.longestPauseMs, speaking_rate_wpm: draft.observations.speakingRateWpm, interruption_count: draft.observations.interruptionCount },
      }),
    });
    if (!response.ok) return { recording: null, error: await apiError(response) };
    return { recording: normalizeVoiceRecording(await response.json() as ApiVoiceRecording) };
  } catch (cause) {
    return { recording: null, error: cause instanceof Error ? cause.message : "Не удалось сохранить аудио" };
  }
}

export async function getVoiceRecordings(sessionId: string): Promise<{ recordings: VoiceRecording[]; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/voice-recordings`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return { recordings: [], error: await apiError(response) };
    const payload = await response.json() as { recordings: ApiVoiceRecording[] };
    return { recordings: payload.recordings.map(normalizeVoiceRecording) };
  } catch (cause) {
    return { recordings: [], error: cause instanceof Error ? cause.message : "Не удалось загрузить аудио" };
  }
}

export async function deleteVoiceRecording(sessionId: string, recordingId: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/voice-recordings/${encodeURIComponent(recordingId)}`, { method: "DELETE", headers: mutationHeaders(), credentials: "include" });
    return response.ok ? { ok: true } : { ok: false, error: await apiError(response) };
  } catch (cause) {
    return { ok: false, error: cause instanceof Error ? cause.message : "Не удалось удалить аудио" };
  }
}

export async function checkSimulationHypothesis(sessionId: string, text: string): Promise<HypothesisResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/simulation/hypotheses`, { method: "POST", headers: mutationHeaders(), credentials: "include", body: JSON.stringify({ text }) });
    if (!response.ok) return { hypothesis: null, error: await apiError(response) };
    const payload = await response.json() as { hypothesis: ApiSimulation["hypotheses"][number]; simulation: ApiSimulation };
    const simulation = normalizeSimulation(payload.simulation, responseServerTime(response, payload.simulation.server_time));
    return { hypothesis: simulation.hypotheses.find((item) => item.id === payload.hypothesis.id) ?? null, simulation };
  } catch (cause) {
    return { hypothesis: null, error: cause instanceof Error ? cause.message : "Не удалось проверить гипотезу" };
  }
}

function normalizeCoachBudget(payload: { used_tokens: number; remaining_tokens: number; used_calls: number; remaining_calls: number }): CoachBudget {
  return { usedTokens: payload.used_tokens, remainingTokens: payload.remaining_tokens, usedCalls: payload.used_calls, remainingCalls: payload.remaining_calls };
}

type ApiPrebrief = {
  id: string | null; session_id: string; saved: boolean; inherited_from_attempt?: number | null; updated_at?: string | null;
  focus_skill: PrebriefWorksheet["focusSkill"]; goal: string; interests: string[]; participant_batna: string; participant_reservation: string; planned_questions: string[];
};

function normalizePrebrief(payload: ApiPrebrief): PrebriefWorksheet {
  return {
    id: payload.id,
    sessionId: payload.session_id,
    saved: payload.saved,
    inheritedFromAttempt: payload.inherited_from_attempt ?? null,
    updatedAt: payload.updated_at ?? null,
    focusSkill: payload.focus_skill,
    goal: payload.goal,
    interests: payload.interests,
    participantBatna: payload.participant_batna,
    participantReservation: payload.participant_reservation,
    plannedQuestions: payload.planned_questions,
  };
}

function prebriefPayload(value: PrebriefWorksheetInput) {
  return { focus_skill: value.focusSkill, goal: value.goal, interests: value.interests, participant_batna: value.participantBatna, participant_reservation: value.participantReservation, planned_questions: value.plannedQuestions };
}

export async function getCoachPrebrief(sessionId: string): Promise<{ worksheet: PrebriefWorksheet | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/coach/prebrief`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return { worksheet: null, error: await apiError(response) };
    return { worksheet: normalizePrebrief(await response.json() as ApiPrebrief) };
  } catch (cause) {
    return { worksheet: null, error: cause instanceof Error ? cause.message : "Не удалось загрузить подготовку" };
  }
}

export async function saveCoachPrebrief(sessionId: string, value: PrebriefWorksheetInput): Promise<{ worksheet: PrebriefWorksheet | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/coach/prebrief`, { method: "POST", headers: mutationHeaders(), credentials: "include", body: JSON.stringify(prebriefPayload(value)) });
    if (!response.ok) return { worksheet: null, error: await apiError(response) };
    return { worksheet: normalizePrebrief(await response.json() as ApiPrebrief) };
  } catch (cause) {
    return { worksheet: null, error: cause instanceof Error ? cause.message : "Не удалось сохранить подготовку" };
  }
}

export async function requestCoachHint(sessionId: string, draft: string, skillId?: PrebriefWorksheet["focusSkill"]): Promise<{ hint: CoachHint | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/coach/hint`, { method: "POST", headers: mutationHeaders(), credentials: "include", body: JSON.stringify({ draft, ...(skillId ? { skill_id: skillId } : {}), mode: "socratic" }) });
    if (!response.ok) return { hint: null, error: await apiError(response) };
    const payload = await response.json() as { question: string; skill_id: CoachHint["skillId"]; mode: "socratic"; provider: CoachHint["provider"]; fallback: boolean; cached: boolean; role_aligned: true; official_outcome_unchanged: true; budget: { used_tokens: number; remaining_tokens: number; used_calls: number; remaining_calls: number } };
    return { hint: { question: payload.question, skillId: payload.skill_id, mode: payload.mode, provider: payload.provider, fallback: payload.fallback, cached: payload.cached, roleAligned: payload.role_aligned, officialOutcomeUnchanged: payload.official_outcome_unchanged, budget: normalizeCoachBudget(payload.budget) } };
  } catch (cause) {
    return { hint: null, error: cause instanceof Error ? cause.message : "Тренер временно недоступен" };
  }
}

export async function requestCoachRewrite(sessionId: string, messageId: string, revisedText: string): Promise<{ rewrite: CoachRewrite | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/coach/rewrite`, { method: "POST", headers: mutationHeaders(), credentials: "include", body: JSON.stringify({ message_id: messageId, revised_text: revisedText }) });
    if (!response.ok) return { rewrite: null, error: await apiError(response) };
    const payload = await response.json() as {
      official_message_id: string; original_text: string; revised_text: string; possible_opponent_reply: string; analysis: string;
      impacts: Array<{ skill_id: CoachRewrite["impacts"][number]["skillId"]; title: string; effect: CoachRewrite["impacts"][number]["effect"]; explanation: string }>;
      provider: CoachRewrite["provider"]; fallback: boolean; cached: boolean; role_aligned: true; official_transcript_changed: false; official_outcome_unchanged: true;
      budget: { used_tokens: number; remaining_tokens: number; used_calls: number; remaining_calls: number };
    };
    return { rewrite: { officialMessageId: payload.official_message_id, originalText: payload.original_text, revisedText: payload.revised_text, possibleOpponentReply: payload.possible_opponent_reply, analysis: payload.analysis, impacts: payload.impacts.map((item) => ({ skillId: item.skill_id, title: item.title, effect: item.effect, explanation: item.explanation })), provider: payload.provider, fallback: payload.fallback, cached: payload.cached, roleAligned: payload.role_aligned, officialTranscriptChanged: payload.official_transcript_changed, officialOutcomeUnchanged: payload.official_outcome_unchanged, budget: normalizeCoachBudget(payload.budget) } };
  } catch (cause) {
    return { rewrite: null, error: cause instanceof Error ? cause.message : "Альтернативная ветка недоступна" };
  }
}

export async function getPersonalizedDrill(sessionId: string): Promise<{ drill: PersonalizedMiniDrill | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/coach/drill`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return { drill: null, error: await apiError(response) };
    const payload = await response.json() as { id: string; session_id: string; skill_id: PersonalizedMiniDrill["skillId"]; title: string; duration_minutes: number; prompt: string; source_turn?: number | null; source_quote?: string | null; instructions: string[]; success_checklist: string[]; suggested_template: string; official_outcome_unchanged: true };
    return { drill: { id: payload.id, sessionId: payload.session_id, skillId: payload.skill_id, title: payload.title, durationMinutes: payload.duration_minutes, prompt: payload.prompt, sourceTurn: payload.source_turn ?? null, sourceQuote: payload.source_quote ?? null, instructions: payload.instructions, successChecklist: payload.success_checklist, suggestedTemplate: payload.suggested_template, officialOutcomeUnchanged: payload.official_outcome_unchanged } };
  } catch (cause) {
    return { drill: null, error: cause instanceof Error ? cause.message : "Упражнение недоступно" };
  }
}

export async function completePersonalizedDrill(sessionId: string, answer: string): Promise<{ feedback: AdaptiveDrillFeedback | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/coach/drill/complete`, { method: "POST", headers: mutationHeaders(), credentials: "include", body: JSON.stringify({ answer }) });
    if (!response.ok) return { feedback: null, error: await apiError(response) };
    const payload = await response.json() as { drill_id: string; skill_id: AdaptiveDrillFeedback["skillId"]; score: number; passed: boolean; feedback: string; checks: Array<{ title: string; met: boolean }>; official_outcome_unchanged: true };
    return { feedback: { drillId: payload.drill_id, skillId: payload.skill_id, score: payload.score, passed: payload.passed, feedback: payload.feedback, checks: payload.checks, officialOutcomeUnchanged: payload.official_outcome_unchanged } };
  } catch (cause) {
    return { feedback: null, error: cause instanceof Error ? cause.message : "Не удалось проверить упражнение" };
  }
}

export async function getAdaptiveCoachSummary(sessionId: string): Promise<{ summary: AdaptiveCoachSummary | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/coach/summary`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return { summary: null, error: await apiError(response) };
    const payload = await response.json() as { session_id: string; focus_skill: AdaptiveCoachSummary["focusSkill"]; hint_count: number; rewrite_count: number; drill_completed: boolean; previous_skill_score?: number | null; current_skill_score?: number | null; skill_delta?: number | null; official_outcome_unchanged: true; budget: { used_tokens: number; remaining_tokens: number; used_calls: number; remaining_calls: number } };
    return { summary: { sessionId: payload.session_id, focusSkill: payload.focus_skill, hintCount: payload.hint_count, rewriteCount: payload.rewrite_count, drillCompleted: payload.drill_completed, previousSkillScore: payload.previous_skill_score ?? null, currentSkillScore: payload.current_skill_score ?? null, skillDelta: payload.skill_delta ?? null, officialOutcomeUnchanged: payload.official_outcome_unchanged, budget: normalizeCoachBudget(payload.budget) } };
  } catch (cause) {
    return { summary: null, error: cause instanceof Error ? cause.message : "Сводка тренера недоступна" };
  }
}

export async function completeAndGetReport(sessionId: string | null): Promise<ReportResult> {
  const baseUrl = apiBaseUrl();
  if (!sessionId) return { report: demoReport, source: "demo" };
  try {
    const completed = await fetch(`${baseUrl}/api/v1/sessions/${sessionId}/complete`, { method: "POST", headers: mutationHeaders(), credentials: "include" });
    if (!completed.ok) throw new Error(`Завершение сессии: ${completed.status}`);
    const response = await fetch(`${baseUrl}/api/v1/sessions/${sessionId}/report`, { credentials: "include" });
    if (!response.ok) throw new Error(`Получение отчёта: ${response.status}`);
    const payload = (await response.json()) as ApiReport;
    const coaching = payload.coaching ? {
      provider: payload.coaching.provider,
      model: payload.coaching.model ?? null,
      fallback: payload.coaching.fallback,
      reason: payload.coaching.reason ?? null,
      summary: payload.coaching.summary,
      points: (payload.coaching.points ?? []).map((item) => ({ turn: item.turn ?? null, quote: item.quote ?? null, problem: item.problem, betterApproach: item.better_approach, suggestedText: item.suggested_text })),
    } : null;
    const report: Report = {
      sessionId: payload.session_id, scenarioId: payload.scenario_id, scenarioVersionId: payload.scenario_version_id, rubricVersion: payload.rubric_version, evaluatorVersion: payload.evaluator_version, status: payload.status,
      score: payload.score, level: payload.level, label: payload.label, summary: payload.summary,
      outcome: { kind: payload.outcome.kind, label: payload.outcome.label, description: payload.outcome.description, participantUtility: payload.outcome.participant_utility ?? null, batnaUtility: payload.outcome.batna_utility ?? null, meetsBatna: payload.outcome.meets_batna ?? null, reservationRespected: payload.outcome.reservation_respected ?? null, acceptedTerms: normalizeAcceptedTerms(payload.outcome.accepted_terms) },
      blocks: payload.blocks.map((b) => ({ id: b.id, title: b.title, score: b.score, maxScore: b.max_score, explanation: b.explanation, criteria: b.criteria.map((c) => ({ id: c.id, title: c.title, score: c.score, maxScore: c.max_score, explanation: c.explanation, evidence: c.evidence.map((e) => ({ messageId: e.message_id, turn: e.turn, quote: e.quote })) })) })),
      penalties: payload.penalties.map((p) => ({ ...p, evidence: p.evidence.map((e) => ({ messageId: e.message_id, turn: e.turn, quote: e.quote })) })),
      strengths: payload.strengths.map((s) => ({ ...s, evidence: s.evidence.map((e) => ({ messageId: e.message_id, turn: e.turn, quote: e.quote })) })),
      improvements: payload.improvements.map((i) => ({ priority: i.priority, title: i.title, originalQuote: i.original_quote, suggestedText: i.suggested_text, rationale: i.rationale, indicatorId: i.indicator_id })),
      taskChecks: (payload.task_checks ?? []).map((item) => ({ id: item.id, title: item.title, status: item.status, explanation: item.explanation, acceptedValue: item.accepted_value ?? null })),
      coaching,
      trajectory: payload.trajectory,
      methodology: { rubricVersion: payload.methodology.rubric_version, formula: payload.methodology.formula, rawScore: payload.methodology.raw_score, penaltyPoints: payload.methodology.penalty_points, scoreCap: payload.methodology.score_cap ?? null, disclaimer: payload.methodology.disclaimer },
      simulation: payload.simulation ? { participantSkillScore: payload.simulation.participant_skill_score, environmentPressureScore: payload.simulation.environment_pressure_score, eventCount: payload.simulation.event_count, timedOutDecisions: payload.simulation.timed_out_decisions, aiParticipants: payload.simulation.ai_participants, phaseReached: payload.simulation.phase_reached, mode: payload.simulation.mode, interpretation: payload.simulation.interpretation } : null,
      nextStep: payload.next_step,
    };
    return { report, source: "api" };
  } catch (cause) {
    return { report: demoReport, source: "demo", error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

type ApiPeerReviewAssignment = {
  assignment_id: string;
  scenario_id: string;
  scenario_title: string;
  anonymized: true;
  double_blind: true;
  participant_alias: string;
  reviewer_alias: string;
  language: "ru" | "en";
  difficulty: "easy" | "medium" | "hard";
  assignment_kind: "peer" | "calibration";
  review_round: 1 | 2;
  matching_reasons: string[];
  sla: { blocking: false; target_hours: number; due_at: string; fallback: string };
  instructions: string;
  messages: Array<{ id: string; sequence: number; role: "participant" | "opponent"; author_label: string; content: string }>;
  criteria: Array<{ id: string; title: string; description: string; max_score: number; low_score_threshold: number }>;
};

type ApiPeerReviewResult = {
  assignment_id: string;
  peer_score: number;
  automatic_score: number;
  difference: number;
  absolute_difference: number;
  comparison: Array<{ criterion_id: string; title: string; peer_score: number; automatic_score: number; max_score: number; difference: number }>;
  reputation: { points: number; label: string; explanation: string; accuracy: number; evidence_quality: number; helpfulness: number; reviews_completed: number; strictness_neutral: true };
  official_score_unchanged: true;
  assignment_kind: "peer" | "calibration";
  review_round: 1 | 2;
  review_status: "accepted" | "second_review_required" | "resolved" | "calibrated";
  reviews_received: number;
  reviews_required: number;
  second_review_required: boolean;
  queue_non_blocking: true;
  feedback: string;
};

function normalizePeerAssignment(payload: ApiPeerReviewAssignment): PeerReviewAssignment {
  return {
    assignmentId: payload.assignment_id,
    scenarioId: payload.scenario_id,
    scenarioTitle: payload.scenario_title,
    anonymized: payload.anonymized,
    doubleBlind: payload.double_blind,
    participantAlias: payload.participant_alias,
    reviewerAlias: payload.reviewer_alias,
    language: payload.language,
    difficulty: payload.difficulty,
    assignmentKind: payload.assignment_kind,
    reviewRound: payload.review_round,
    matchingReasons: payload.matching_reasons,
    sla: { blocking: payload.sla.blocking, targetHours: payload.sla.target_hours, dueAt: payload.sla.due_at, fallback: payload.sla.fallback },
    instructions: payload.instructions,
    messages: payload.messages.map((item) => ({ id: item.id, sequence: item.sequence, role: item.role, authorLabel: item.author_label, content: item.content })),
    criteria: payload.criteria.map((item) => ({ id: item.id, title: item.title, description: item.description, maxScore: item.max_score, lowScoreThreshold: item.low_score_threshold })),
  };
}

function normalizePeerResult(payload: ApiPeerReviewResult): PeerReviewResult {
  return {
    assignmentId: payload.assignment_id,
    peerScore: payload.peer_score,
    automaticScore: payload.automatic_score,
    difference: payload.difference,
    absoluteDifference: payload.absolute_difference,
    comparison: payload.comparison.map((item) => ({ criterionId: item.criterion_id, title: item.title, peerScore: item.peer_score, automaticScore: item.automatic_score, maxScore: item.max_score, difference: item.difference })),
    reputation: { points: payload.reputation.points, label: payload.reputation.label, explanation: payload.reputation.explanation, accuracy: payload.reputation.accuracy, evidenceQuality: payload.reputation.evidence_quality, helpfulness: payload.reputation.helpfulness, reviewsCompleted: payload.reputation.reviews_completed, strictnessNeutral: payload.reputation.strictness_neutral },
    officialScoreUnchanged: payload.official_score_unchanged,
    assignmentKind: payload.assignment_kind,
    reviewRound: payload.review_round,
    reviewStatus: payload.review_status,
    reviewsReceived: payload.reviews_received,
    reviewsRequired: payload.reviews_required,
    secondReviewRequired: payload.second_review_required,
    queueNonBlocking: payload.queue_non_blocking,
    feedback: payload.feedback,
  };
}

export async function getNextPeerReview(excludeSessionId: string | null, language: "ru" | "en" = "ru", difficulty?: "easy" | "medium" | "hard"): Promise<PeerReviewAssignmentResult> {
  const baseUrl = apiBaseUrl();
  const params = new URLSearchParams({ language });
  if (excludeSessionId) params.set("exclude_session_id", excludeSessionId);
  if (difficulty) params.set("difficulty", difficulty);
  try {
    const response = await fetch(`${baseUrl}/api/v1/peer-reviews/next?${params}`, { signal: AbortSignal.timeout(5000), credentials: "include" });
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    return { assignment: normalizePeerAssignment((await response.json()) as ApiPeerReviewAssignment) };
  } catch (cause) {
    return { assignment: null, error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

type ApiPeerReviewSessionStatus = {
  session_id: string; status: PeerReviewSessionStatus["status"]; peer_review_blocking: false; official_score_unchanged: true;
  reviews_received: number; reviews_required: number; consensus_score: number | null; can_appeal: boolean;
  sla: { blocking: false; target_hours: number; due_at: string; fallback: string };
  reviews: Array<{ assignment_id: string; reviewer_alias: string; peer_score: number | null; review_round: number; status: string; appeal_status: "none" | "pending" | "resolved"; submitted_at: string | null }>;
};

function normalizePeerReviewStatus(payload: ApiPeerReviewSessionStatus): PeerReviewSessionStatus {
  return { sessionId: payload.session_id, status: payload.status, peerReviewBlocking: payload.peer_review_blocking, officialScoreUnchanged: payload.official_score_unchanged, reviewsReceived: payload.reviews_received, reviewsRequired: payload.reviews_required, consensusScore: payload.consensus_score, canAppeal: payload.can_appeal, sla: { blocking: payload.sla.blocking, targetHours: payload.sla.target_hours, dueAt: payload.sla.due_at, fallback: payload.sla.fallback }, reviews: payload.reviews.map((item) => ({ assignmentId: item.assignment_id, reviewerAlias: item.reviewer_alias, peerScore: item.peer_score, reviewRound: item.review_round, status: item.status, appealStatus: item.appeal_status, submittedAt: item.submitted_at })) };
}

export async function getPeerReviewStatus(sessionId: string): Promise<{ status: PeerReviewSessionStatus | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${encodeURIComponent(sessionId)}/peer-review-status`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return { status: null, error: await apiError(response) };
    return { status: normalizePeerReviewStatus(await response.json() as ApiPeerReviewSessionStatus) };
  } catch (cause) {
    return { status: null, error: cause instanceof Error ? cause.message : "Не удалось загрузить статус peer-review" };
  }
}

export async function appealPeerReview(assignmentId: string, reason: string): Promise<{ accepted: boolean; message?: string; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/peer-reviews/${encodeURIComponent(assignmentId)}/appeal`, { method: "POST", headers: mutationHeaders(), credentials: "include", body: JSON.stringify({ reason }) });
    if (!response.ok) return { accepted: false, error: await apiError(response) };
    const payload = await response.json() as { message: string };
    return { accepted: true, message: payload.message };
  } catch (cause) {
    return { accepted: false, error: cause instanceof Error ? cause.message : "Не удалось отправить жалобу" };
  }
}

export async function submitPeerReview(assignmentId: string, items: PeerReviewDraftItem[], overallComment: string): Promise<PeerReviewSubmitResult> {
  const baseUrl = apiBaseUrl();
  try {
    const response = await fetch(`${baseUrl}/api/v1/peer-reviews`, {
      method: "POST",
      headers: mutationHeaders(),
      credentials: "include",
      body: JSON.stringify({
        assignment_id: assignmentId,
        overall_comment: overallComment,
        items: items.map((item) => ({ criterion_id: item.criterionId, score: item.score, message_id: item.messageId, comment: item.comment, suggested_text: item.suggestedText.trim() || null })),
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { detail?: string } | null;
      throw new Error(payload?.detail || `Сервер вернул ${response.status}`);
    }
    return { result: normalizePeerResult((await response.json()) as ApiPeerReviewResult) };
  } catch (cause) {
    return { result: null, error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

type ApiAttemptSnapshot = {
  session_id: string; attempt_number: number; rubric_version: string; evaluator_version: string; score: number; level: string; outcome_kind: "agreement" | "impasse" | "walk_away" | "incomplete"; outcome_label: string; turns: number; tasks_met: number; tasks_total: number; completed_at: string;
};

type ApiAttemptComparison = {
  series_id: string;
  scenario_id: string;
  scenario_title: string;
  previous: ApiAttemptSnapshot;
  current: ApiAttemptSnapshot;
  score_delta: number;
  outcome_changed: boolean;
  block_deltas: Array<{ block_id: string; title: string; previous_score: number; current_score: number; max_score: number; delta: number }>;
  task_deltas: Array<{ task_id: string; title: string; previous_status: "met" | "not_met"; current_status: "met" | "not_met"; change: "improved" | "regressed" | "unchanged" }>;
  improved_blocks: string[];
  regressed_blocks: string[];
  resolved_focus: string[];
  new_focus: string[];
  summary: string;
  next_step: string;
};

type ApiHistoricalAttemptComparison = {
  series_id: string;
  scenario_id: string;
  scenario_title: string;
  previous: ApiAttemptSnapshot;
  current: ApiAttemptSnapshot;
  versions_match: boolean;
  summary: string;
};

function normalizeAttemptSnapshot(item: ApiAttemptSnapshot): AttemptComparison["previous"] {
  return { sessionId: item.session_id, attemptNumber: item.attempt_number, rubricVersion: item.rubric_version, evaluatorVersion: item.evaluator_version, score: item.score, level: item.level, outcomeKind: item.outcome_kind, outcomeLabel: item.outcome_label, turns: item.turns, tasksMet: item.tasks_met, tasksTotal: item.tasks_total, completedAt: item.completed_at };
}

function normalizeAttemptComparison(payload: ApiAttemptComparison): AttemptComparison {
  return {
    seriesId: payload.series_id,
    scenarioId: payload.scenario_id,
    scenarioTitle: payload.scenario_title,
    previous: normalizeAttemptSnapshot(payload.previous),
    current: normalizeAttemptSnapshot(payload.current),
    scoreDelta: payload.score_delta,
    outcomeChanged: payload.outcome_changed,
    blockDeltas: payload.block_deltas.map((item) => ({ blockId: item.block_id, title: item.title, previousScore: item.previous_score, currentScore: item.current_score, maxScore: item.max_score, delta: item.delta })),
    taskDeltas: payload.task_deltas.map((item) => ({ taskId: item.task_id, title: item.title, previousStatus: item.previous_status, currentStatus: item.current_status, change: item.change })),
    improvedBlocks: payload.improved_blocks,
    regressedBlocks: payload.regressed_blocks,
    resolvedFocus: payload.resolved_focus,
    newFocus: payload.new_focus,
    summary: payload.summary,
    nextStep: payload.next_step,
  };
}

function normalizeHistoricalAttemptComparison(payload: ApiHistoricalAttemptComparison): HistoricalAttemptComparison {
  return {
    seriesId: payload.series_id,
    scenarioId: payload.scenario_id,
    scenarioTitle: payload.scenario_title,
    previous: normalizeAttemptSnapshot(payload.previous),
    current: normalizeAttemptSnapshot(payload.current),
    versionsMatch: payload.versions_match,
    summary: payload.summary,
  };
}

export async function retrySession(sessionId: string | null): Promise<SessionStartResult> {
  if (!sessionId) return { sessionId: null, source: "demo", error: "Исходная API-сессия недоступна" };
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${sessionId}/retry`, { method: "POST", headers: mutationHeaders(), credentials: "include" });
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    const payload = (await response.json()) as { id: string; attempt_number: number; simulation: ApiSimulation };
    return { sessionId: payload.id, attemptNumber: payload.attempt_number, source: "api", simulation: normalizeSimulation(payload.simulation, responseServerTime(response, payload.simulation.server_time)) };
  } catch (cause) {
    return { sessionId: null, source: "demo", error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

export async function getAttemptComparison(sessionId: string | null): Promise<AttemptComparisonResult> {
  if (!sessionId) return { comparison: null };
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/sessions/${sessionId}/comparison`, { credentials: "include" });
    if (response.status === 409) {
      const payload = await response.json().catch(() => null) as { detail?: string } | null;
      if (payload?.detail !== "rubric_version_mismatch" && payload?.detail !== "evaluator_version_mismatch") return { comparison: null };
      const historicalResponse = await fetch(`${apiBaseUrl()}/api/v1/sessions/${sessionId}/comparison/historical`, { credentials: "include" });
      if (!historicalResponse.ok) throw new Error(`Сервер вернул ${historicalResponse.status}`);
      const historical = normalizeHistoricalAttemptComparison((await historicalResponse.json()) as ApiHistoricalAttemptComparison);
      if (historical.versionsMatch) throw new Error("Сервер не подтвердил различие версий для исторического сравнения");
      return { comparison: null, historical };
    }
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}`);
    return { comparison: normalizeAttemptComparison((await response.json()) as ApiAttemptComparison) };
  } catch (cause) {
    return { comparison: null, error: cause instanceof Error ? cause.message : "Неизвестная ошибка" };
  }
}

type ApiAuth = {
  account: { id: string; email: string; display_name: string; roles: string[]; created_at: string };
  recovery_code?: string | null;
};

function normalizeAccount(payload: ApiAuth["account"]): AccountProfile {
  return { id: payload.id, email: payload.email, displayName: payload.display_name, roles: payload.roles, createdAt: payload.created_at };
}

async function authRequest(path: string, body: Record<string, unknown>): Promise<AuthResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
    if (!response.ok) return { account: null, error: await apiError(response) };
    const payload = (await response.json()) as ApiAuth;
    return { account: normalizeAccount(payload.account), recoveryCode: payload.recovery_code ?? null };
  } catch (cause) {
    return { account: null, error: cause instanceof Error ? cause.message : "Не удалось связаться с сервером" };
  }
}

export function registerAccount(email: string, displayName: string, password: string, claimSessionId: string | null): Promise<AuthResult> {
  return authRequest("/api/v1/auth/register", { email, display_name: displayName, password, claim_session_id: claimSessionId });
}

export function loginAccount(email: string, password: string, claimSessionId: string | null): Promise<AuthResult> {
  return authRequest("/api/v1/auth/login", { email, password, claim_session_id: claimSessionId });
}

export async function getCurrentAccount(): Promise<AccountProfile | null> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/auth/me`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return null;
    return normalizeAccount(((await response.json()) as ApiAuth).account);
  } catch {
    return null;
  }
}

export async function logoutAccount(): Promise<boolean> {
  const response = await fetch(`${apiBaseUrl()}/api/v1/auth/logout`, { method: "POST", headers: mutationHeaders(), credentials: "include" }).catch(() => null);
  return Boolean(response?.ok);
}

export async function recoverAccount(email: string, recoveryCode: string, newPassword: string): Promise<{ recoveryCode?: string; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/auth/recover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, recovery_code: recoveryCode, new_password: newPassword }),
    });
    if (!response.ok) return { error: await apiError(response) };
    return { recoveryCode: ((await response.json()) as { recovery_code: string }).recovery_code };
  } catch (cause) {
    return { error: cause instanceof Error ? cause.message : "Не удалось связаться с сервером" };
  }
}

export async function getAccountHistory(): Promise<{ history: AccountHistory | null; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/me/history`, { credentials: "include", cache: "no-store" });
    if (!response.ok) return { history: null, error: await apiError(response) };
    const payload = await response.json() as {
      negotiations: Array<{ session_id: string; series_id: string; attempt_number: number; scenario_id: string; topic: string; status: "active" | "completed"; outcome: string | null; score: number | null; created_at: string; completed_at: string | null }>;
      peer_reviews: Array<{ assignment_id: string; scenario_title: string; status: string; peer_score: number | null; reputation_points: number | null; assignment_kind: "peer" | "calibration"; review_status: string; created_at: string; submitted_at: string | null }>;
    };
    return { history: {
      negotiations: payload.negotiations.map((item) => ({ sessionId: item.session_id, seriesId: item.series_id, attemptNumber: item.attempt_number, scenarioId: item.scenario_id, topic: item.topic, status: item.status, outcome: item.outcome, score: item.score, createdAt: item.created_at, completedAt: item.completed_at })),
      peerReviews: payload.peer_reviews.map((item) => ({ assignmentId: item.assignment_id, scenarioTitle: item.scenario_title, status: item.status, peerScore: item.peer_score, reputationPoints: item.reputation_points, assignmentKind: item.assignment_kind, reviewStatus: item.review_status, createdAt: item.created_at, submittedAt: item.submitted_at })),
    } };
  } catch (cause) {
    return { history: null, error: cause instanceof Error ? cause.message : "Не удалось связаться с сервером" };
  }
}

export async function deleteAccount(password: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/auth/account`, {
      method: "DELETE",
      headers: mutationHeaders(),
      credentials: "include",
      body: JSON.stringify({ password }),
    });
    return response.ok ? { ok: true } : { ok: false, error: await apiError(response) };
  } catch (cause) {
    return { ok: false, error: cause instanceof Error ? cause.message : "Не удалось связаться с сервером" };
  }
}

type ApiLearningDashboard = {
  rubric_version: string | null;
  comparable_sessions: number;
  excluded_incompatible_sessions: number;
  goal: { skill_id: string; target_score: number; weekly_sessions: number; updated_at: string } | null;
  skill_map: Array<{ id: string; title: string; description: string; score: number | null; previous_score: number | null; delta: number | null; attempts: number; status: "new" | "focus" | "developing" | "strong"; last_practiced_at: string | null; next_due_at: string | null; due: boolean; evidence_reason: string }>;
  weekly_progress: Array<{ period_start: string; attempts: number; scores: Record<string, number> }>;
  scenario_progress: Array<{ scenario_id: string; scenario_title: string; attempts: number; scores: Record<string, number> }>;
  recommendation: { skill_id: string; scenario_id: string; scenario_title: string; reason: string };
  recommended_drill: { id: string; skill_id: string; title: string; duration_minutes: number; prompt: string; instructions: string[]; success_checklist: string[]; suggested_template: string };
};

function normalizeLearningDashboard(payload: ApiLearningDashboard): LearningDashboard {
  return {
    rubricVersion: payload.rubric_version,
    comparableSessions: payload.comparable_sessions,
    excludedIncompatibleSessions: payload.excluded_incompatible_sessions,
    goal: payload.goal ? { skillId: payload.goal.skill_id, targetScore: payload.goal.target_score, weeklySessions: payload.goal.weekly_sessions, updatedAt: payload.goal.updated_at } : null,
    skillMap: payload.skill_map.map((item) => ({ id: item.id, title: item.title, description: item.description, score: item.score, previousScore: item.previous_score, delta: item.delta, attempts: item.attempts, status: item.status, lastPracticedAt: item.last_practiced_at, nextDueAt: item.next_due_at, due: item.due, evidenceReason: item.evidence_reason })),
    weeklyProgress: payload.weekly_progress.map((item) => ({ periodStart: item.period_start, attempts: item.attempts, scores: item.scores })),
    scenarioProgress: payload.scenario_progress.map((item) => ({ scenarioId: item.scenario_id, scenarioTitle: item.scenario_title, attempts: item.attempts, scores: item.scores })),
    recommendation: { skillId: payload.recommendation.skill_id, scenarioId: payload.recommendation.scenario_id, scenarioTitle: payload.recommendation.scenario_title, reason: payload.recommendation.reason },
    recommendedDrill: { id: payload.recommended_drill.id, skillId: payload.recommended_drill.skill_id, title: payload.recommended_drill.title, durationMinutes: payload.recommended_drill.duration_minutes, prompt: payload.recommended_drill.prompt, instructions: payload.recommended_drill.instructions, successChecklist: payload.recommended_drill.success_checklist, suggestedTemplate: payload.recommended_drill.suggested_template },
  };
}

async function learningRequest(path: string, body?: Record<string, unknown>): Promise<LearningDashboardResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method: body ? "POST" : "GET",
      headers: body ? mutationHeaders() : undefined,
      credentials: "include",
      cache: "no-store",
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) return { dashboard: null, error: await apiError(response) };
    return { dashboard: normalizeLearningDashboard(await response.json() as ApiLearningDashboard) };
  } catch (cause) {
    return { dashboard: null, error: cause instanceof Error ? cause.message : "Не удалось загрузить траекторию" };
  }
}

export function getLearningDashboard(): Promise<LearningDashboardResult> {
  return learningRequest("/api/v1/me/learning");
}

export function saveLearningGoal(skillId: string, targetScore: number, weeklySessions: number): Promise<LearningDashboardResult> {
  return learningRequest("/api/v1/me/learning-goal", { skill_id: skillId, target_score: targetScore, weekly_sessions: weeklySessions });
}

export function completeLearningDrill(drillId: string, selfRating: number): Promise<LearningDashboardResult> {
  return learningRequest(`/api/v1/me/drills/${encodeURIComponent(drillId)}/complete`, { self_rating: selfRating });
}

type ApiMotivationDashboard = {
  enabled: boolean; team_opt_in: boolean; timezone?: string;
  streak: { current: number; longest: number; last_practiced_on: string | null };
  skill_tree: Array<{ id: string; title: string; level: number; unlocked: boolean; unlock_reason: string; next_requirement: string | null }>;
  achievements: Array<{ id: string; title: string; description: string; earned_at: string }>;
  daily_challenge: { date: string; scenario_id: string; scenario_title: string; seed: number; skill_id: string; completed: boolean; session_id: string | null };
  weekly_challenge: { week_start: string; scenario_id: string; scenario_title: string; seed: number; skill_id: string; completed: boolean; session_id: string | null };
  team: { id: string; name: string; invite_code: string; members: number } | null;
  leaderboard: Array<{ rank: number; team_id: string; team_name: string; members: number; points: number; completed_sessions: number }>;
};

function normalizeMotivation(payload: ApiMotivationDashboard): MotivationDashboard {
  return {
    enabled: payload.enabled, teamOptIn: payload.team_opt_in,
    streak: { current: payload.streak.current, longest: payload.streak.longest, lastPracticedOn: payload.streak.last_practiced_on },
    skillTree: payload.skill_tree.map((item) => ({ id: item.id, title: item.title, level: item.level, unlocked: item.unlocked, unlockReason: item.unlock_reason, nextRequirement: item.next_requirement })),
    achievements: payload.achievements.map((item) => ({ id: item.id, title: item.title, description: item.description, earnedAt: item.earned_at })),
    dailyChallenge: { date: payload.daily_challenge.date, scenarioId: payload.daily_challenge.scenario_id, scenarioTitle: payload.daily_challenge.scenario_title, seed: payload.daily_challenge.seed, skillId: payload.daily_challenge.skill_id, completed: payload.daily_challenge.completed, sessionId: payload.daily_challenge.session_id },
    weeklyChallenge: { weekStart: payload.weekly_challenge.week_start, scenarioId: payload.weekly_challenge.scenario_id, scenarioTitle: payload.weekly_challenge.scenario_title, seed: payload.weekly_challenge.seed, skillId: payload.weekly_challenge.skill_id, completed: payload.weekly_challenge.completed, sessionId: payload.weekly_challenge.session_id },
    team: payload.team ? { id: payload.team.id, name: payload.team.name, inviteCode: payload.team.invite_code, members: payload.team.members } : null,
    leaderboard: payload.leaderboard.map((item) => ({ rank: item.rank, teamId: item.team_id, teamName: item.team_name, members: item.members, points: item.points, completedSessions: item.completed_sessions })),
  };
}

async function motivationRequest(path: string, body?: Record<string, unknown>): Promise<MotivationDashboardResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, { method: body ? "POST" : "GET", headers: body ? mutationHeaders() : undefined, credentials: "include", cache: "no-store", ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) return { dashboard: null, error: await apiError(response) };
    return { dashboard: normalizeMotivation(await response.json() as ApiMotivationDashboard) };
  } catch (cause) {
    return { dashboard: null, error: cause instanceof Error ? cause.message : "Не удалось загрузить мотивационный профиль" };
  }
}

export function getMotivationDashboard(): Promise<MotivationDashboardResult> { return motivationRequest("/api/v1/me/motivation"); }
export function saveMotivationPreferences(enabled: boolean, teamOptIn: boolean): Promise<MotivationDashboardResult> {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  return motivationRequest("/api/v1/me/motivation/preferences", { enabled, team_opt_in: teamOptIn, timezone });
}
export function createMotivationTeam(name: string): Promise<MotivationDashboardResult> { return motivationRequest("/api/v1/me/motivation/team/create", { name }); }
export function joinMotivationTeam(inviteCode: string): Promise<MotivationDashboardResult> { return motivationRequest("/api/v1/me/motivation/team/join", { invite_code: inviteCode }); }
export function leaveMotivationTeam(): Promise<MotivationDashboardResult> { return motivationRequest("/api/v1/me/motivation/team/leave", {}); }

export async function startMotivationChallenge(kind: "daily" | "weekly"): Promise<SessionStartResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/me/motivation/challenges/${kind}/start`, { method: "POST", headers: mutationHeaders(), credentials: "include" });
    if (!response.ok) return { sessionId: null, source: "api", error: await apiError(response) };
    const payload = await response.json() as { id: string; attempt_number?: number; scenario_id: string; configuration: { topic: string }; simulation: ApiSimulation };
    return { sessionId: payload.id, attemptNumber: payload.attempt_number ?? 1, scenarioId: payload.scenario_id, topic: payload.configuration.topic, source: "api", simulation: normalizeSimulation(payload.simulation, responseServerTime(response, payload.simulation.server_time)) };
  } catch (cause) { return { sessionId: null, source: "api", error: cause instanceof Error ? cause.message : "Не удалось начать вызов" }; }
}

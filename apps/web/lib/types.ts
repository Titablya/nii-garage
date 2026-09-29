export type SimulationSettings = {
  enabled: boolean;
  mode: "meeting" | "correspondence" | "escalation";
  opponentStrategy: "analytical" | "collaborative" | "competitive" | "cautious";
  aiParticipants: 1 | 2 | 3;
  eventIntensity: 0 | 1 | 2;
  decisionTimeSeconds: number;
  seed: number | null;
};
export type SessionConfiguration = { topic: string; context: string; participantRole: string; opponentRole: string; objective: string; difficulty: "easy" | "medium" | "hard"; tone: "cooperative" | "businesslike" | "firm"; maxTurns: number; simulation: SimulationSettings };
export type Scenario = {
  id: string;
  title: string;
  subtitle: string;
  description: string;
  role: string;
  opponent: string;
  duration: string;
  skills: string[];
  objective: string;
  context: string;
  tasks: { id: string; title: string; description: string }[];
  configurable?: boolean; tone?: SessionConfiguration["tone"]; difficulty?: SessionConfiguration["difficulty"]; maxTurns?: number;
  industry?: string; negotiationType?: string; theme?: string; roleTags?: string[]; methods?: string[];
  source?: "curated" | "custom"; revision?: number;
};

export type ScenarioDraftInput = {
  seriesId?: string;
  templateId: string;
  title: string;
  situation: string;
  participantRole: string;
  opponentRole: string;
  objective: string;
  industry: string;
  theme: string;
  difficulty: SessionConfiguration["difficulty"];
  tone: SessionConfiguration["tone"];
  estimatedMinutes: number;
  maxTurns: number;
  stakesLevel: "low" | "standard" | "high";
};

export type ScenarioDraft = {
  id: string;
  seriesId: string;
  version: number;
  scenario: Scenario;
  validation: {
    valid: true;
    checkedIssues: number;
    overlappingIssues: number;
    noOverlapIssues: number;
    alternativeIntegrity: true;
    reservationIntegrity: true;
    hiddenFieldsExposed: false;
  };
  createdAt: string;
};

export type ScenarioTextSuggestion = {
  title: string;
  situation: string;
  objective: string;
  provider: "gemini" | "deterministic";
  fallback: boolean;
};

export type ChatMessage = {
  id: string;
  author: "user" | "opponent" | "system";
  text: string;
  timestamp: string;
  speakerId?: string | null;
  speakerLabel?: string | null;
  messageKind?: "dialogue" | "event" | "timeout";
};

export type SimulationEvent = { id: string; kind: "budget" | "deadline" | "authority" | "resource"; title: string; description: string; triggerTurn: number; severity: number; zopaPreserved: true };
export type SimulationDisclosure = { id: string; text: string; sourceTurn: number };
export type SimulationHypothesis = { id: string; text: string; status: "confirmed" | "refuted" | "insufficient"; explanation: string; evidenceFactId: string | null; checkedAt: string };
export type SimulationSnapshot = {
  enabled: boolean; seed: number; mode: SimulationSettings["mode"];
  phase: "preparation" | "opening" | "exploration" | "exchange" | "commitment";
  decisionTimeSeconds: number; deadlineAt: string | null; serverTime: string;
  timedOutDecisions: number; pressureScore: number;
  events: SimulationEvent[]; disclosures: SimulationDisclosure[]; hypotheses: SimulationHypothesis[];
  opponents: Array<{ id: string; label: string; role: string; strategy: SimulationSettings["opponentStrategy"] }>;
};

export type Evidence = { messageId: string; turn: number; quote: string };
export type ReportCriterion = { id: string; title: string; score: number; maxScore: number; explanation: string; evidence: Evidence[] };
export type ReportBlock = { id: string; title: string; score: number; maxScore: number; explanation: string; criteria: ReportCriterion[] };
export type ReportFinding = { code: string; title: string; explanation: string; points: number; evidence: Evidence[] };
export type ReportPenalty = { id: string; title: string; explanation: string; points: number; occurrences: number; evidence: Evidence[] };
export type ReportImprovement = { priority: number; title: string; originalQuote: string | null; suggestedText: string; rationale: string; indicatorId: string };
export type ReportTaskCheck = { id: string; title: string; status: "met" | "not_met"; explanation: string; acceptedValue: string | null };
export type CoachingPoint = { turn: number | null; quote: string | null; problem: string; betterApproach: string; suggestedText: string };
export type CoachingAnalysis = { provider: "gemini" | "deterministic"; model: string | null; fallback: boolean; reason: string | null; summary: string; points: CoachingPoint[] };
export type Report = {
  sessionId: string; scenarioId: string; scenarioVersionId: string; rubricVersion: string; evaluatorVersion: string; status: string;
  score: number; level: string; label: string; summary: string;
  outcome: { kind: string; label: string; description: string; participantUtility: number | null; batnaUtility: number | null; meetsBatna: boolean | null; reservationRespected: boolean | null; acceptedTerms: string[] };
  blocks: ReportBlock[]; penalties: ReportPenalty[]; strengths: ReportFinding[]; improvements: ReportImprovement[];
  taskChecks: ReportTaskCheck[]; coaching: CoachingAnalysis | null;
  trajectory: { turn: number; trust: number; tension: number; progress: number; relationship: number }[];
  methodology: { rubricVersion: string; formula: string; rawScore: number; penaltyPoints: number; scoreCap: number | null; disclaimer: string };
  simulation: { participantSkillScore: number; environmentPressureScore: number; eventCount: number; timedOutDecisions: number; aiParticipants: number; phaseReached: SimulationSnapshot["phase"]; mode: SimulationSettings["mode"]; interpretation: string } | null;
  nextStep: string;
};

export type SessionStartResult = {
  sessionId: string | null;
  attemptNumber?: number;
  scenarioId?: string;
  topic?: string;
  source: "api" | "demo";
  error?: string;
  simulation?: SimulationSnapshot;
};

export type RestoredSession = {
  sessionId: string;
  scenarioId: string;
  attemptNumber: number;
  configuration: SessionConfiguration;
  status: "active" | "completed";
  messages: ChatMessage[];
  simulation: SimulationSnapshot;
};

export type SessionRestoreResult = {
  session: RestoredSession | null;
  error?: string;
};

export type GenerationMetadata = {
  provider: string;
  model: string | null;
  fallback: boolean;
  reason: string | null;
};

export type MessageResult = {
  reply?: string;
  replies?: ChatMessage[];
  participantMessageId?: string;
  source: "api" | "demo";
  generation: GenerationMetadata;
  sessionStatus?: string;
  simulation?: SimulationSnapshot;
  error?: string;
};

export type VoiceRetention = "do_not_store" | "24_hours" | "30_days";
export type VoiceObservations = {
  pauseCount: number;
  longestPauseMs: number;
  speakingRateWpm: number;
  interruptionCount: number;
};
export type VoiceDraft = {
  blob: Blob;
  mimeType: string;
  durationMs: number;
  retentionPolicy: VoiceRetention;
  observations: VoiceObservations;
};
export type VoiceRecording = {
  id: string;
  sessionId: string;
  messageId: string;
  mimeType: string;
  byteSize: number;
  durationMs: number;
  transcript: string;
  retentionPolicy: Exclude<VoiceRetention, "do_not_store">;
  observations: VoiceObservations;
  audioUrl: string;
  expiresAt: string;
  createdAt: string;
};

export type HypothesisResult = { hypothesis: SimulationHypothesis | null; simulation?: SimulationSnapshot; error?: string };

export type ReportResult = {
  report: Report;
  source: "api" | "demo";
  error?: string;
};

export type PeerReviewMessage = {
  id: string;
  sequence: number;
  role: "participant" | "opponent";
  authorLabel: string;
  content: string;
};

export type PeerReviewCriterion = {
  id: string;
  title: string;
  description: string;
  maxScore: number;
  lowScoreThreshold: number;
};

export type PeerReviewAssignment = {
  assignmentId: string;
  scenarioId: string;
  scenarioTitle: string;
  anonymized: true;
  doubleBlind: true;
  participantAlias: string;
  reviewerAlias: string;
  language: "ru" | "en";
  difficulty: "easy" | "medium" | "hard";
  assignmentKind: "peer" | "calibration";
  reviewRound: 1 | 2;
  matchingReasons: string[];
  sla: { blocking: false; targetHours: number; dueAt: string; fallback: string };
  instructions: string;
  messages: PeerReviewMessage[];
  criteria: PeerReviewCriterion[];
};

export type PeerReviewDraftItem = {
  criterionId: string;
  score: number;
  messageId: string;
  comment: string;
  suggestedText: string;
};

export type PeerReviewResult = {
  assignmentId: string;
  peerScore: number;
  automaticScore: number;
  difference: number;
  absoluteDifference: number;
  comparison: Array<{ criterionId: string; title: string; peerScore: number; automaticScore: number; maxScore: number; difference: number }>;
  reputation: { points: number; label: string; explanation: string; accuracy: number; evidenceQuality: number; helpfulness: number; reviewsCompleted: number; strictnessNeutral: true };
  officialScoreUnchanged: true;
  assignmentKind: "peer" | "calibration";
  reviewRound: 1 | 2;
  reviewStatus: "accepted" | "second_review_required" | "resolved" | "calibrated";
  reviewsReceived: number;
  reviewsRequired: number;
  secondReviewRequired: boolean;
  queueNonBlocking: true;
  feedback: string;
};

export type PeerReviewAssignmentResult = { assignment: PeerReviewAssignment | null; error?: string };
export type PeerReviewSubmitResult = { result: PeerReviewResult | null; error?: string };

export type PeerReviewSessionStatus = {
  sessionId: string;
  status: "waiting" | "reviewed" | "disputed" | "re_reviewing" | "resolved";
  peerReviewBlocking: false;
  officialScoreUnchanged: true;
  reviewsReceived: number;
  reviewsRequired: number;
  consensusScore: number | null;
  canAppeal: boolean;
  sla: { blocking: false; targetHours: number; dueAt: string; fallback: string };
  reviews: Array<{ assignmentId: string; reviewerAlias: string; peerScore: number | null; reviewRound: number; status: string; appealStatus: "none" | "pending" | "resolved"; submittedAt: string | null }>;
};

export type AttemptSnapshot = {
  sessionId: string;
  attemptNumber: number;
  rubricVersion: string;
  evaluatorVersion: string;
  score: number;
  level: string;
  outcomeKind: "agreement" | "impasse" | "walk_away" | "incomplete";
  outcomeLabel: string;
  turns: number;
  tasksMet: number;
  tasksTotal: number;
  completedAt: string;
};

export type AttemptComparison = {
  seriesId: string;
  scenarioId: string;
  scenarioTitle: string;
  previous: AttemptSnapshot;
  current: AttemptSnapshot;
  scoreDelta: number;
  outcomeChanged: boolean;
  blockDeltas: Array<{ blockId: string; title: string; previousScore: number; currentScore: number; maxScore: number; delta: number }>;
  taskDeltas: Array<{ taskId: string; title: string; previousStatus: "met" | "not_met"; currentStatus: "met" | "not_met"; change: "improved" | "regressed" | "unchanged" }>;
  improvedBlocks: string[];
  regressedBlocks: string[];
  resolvedFocus: string[];
  newFocus: string[];
  summary: string;
  nextStep: string;
};

export type HistoricalAttemptComparison = {
  seriesId: string;
  scenarioId: string;
  scenarioTitle: string;
  previous: AttemptSnapshot;
  current: AttemptSnapshot;
  versionsMatch: boolean;
  summary: string;
};

export type AttemptComparisonResult = {
  comparison: AttemptComparison | null;
  historical?: HistoricalAttemptComparison | null;
  error?: string;
};

export type AccountProfile = {
  id: string;
  email: string;
  displayName: string;
  roles: string[];
  createdAt: string;
};

export type AccountHistoryItem = {
  sessionId: string;
  seriesId: string;
  attemptNumber: number;
  scenarioId: string;
  topic: string;
  status: "active" | "completed";
  outcome: string | null;
  score: number | null;
  createdAt: string;
  completedAt: string | null;
};

export type AccountPeerReviewItem = {
  assignmentId: string;
  scenarioTitle: string;
  status: string;
  peerScore: number | null;
  reputationPoints: number | null;
  assignmentKind: "peer" | "calibration";
  reviewStatus: string;
  createdAt: string;
  submittedAt: string | null;
};

export type AccountHistory = {
  negotiations: AccountHistoryItem[];
  peerReviews: AccountPeerReviewItem[];
};

export type AuthResult = {
  account: AccountProfile | null;
  recoveryCode?: string | null;
  error?: string;
};

export type LearningGoal = {
  skillId: string;
  targetScore: number;
  weeklySessions: number;
  updatedAt: string;
};

export type SkillProgress = {
  id: string;
  title: string;
  description: string;
  score: number | null;
  previousScore: number | null;
  delta: number | null;
  attempts: number;
  status: "new" | "focus" | "developing" | "strong";
  lastPracticedAt: string | null;
  nextDueAt: string | null;
  due: boolean;
  evidenceReason: string;
};

export type DrillDefinition = {
  id: string;
  skillId: string;
  title: string;
  durationMinutes: number;
  prompt: string;
  instructions: string[];
  successChecklist: string[];
  suggestedTemplate: string;
};

export type LearningDashboard = {
  rubricVersion: string | null;
  comparableSessions: number;
  excludedIncompatibleSessions: number;
  goal: LearningGoal | null;
  skillMap: SkillProgress[];
  weeklyProgress: Array<{ periodStart: string; attempts: number; scores: Record<string, number> }>;
  scenarioProgress: Array<{ scenarioId: string; scenarioTitle: string; attempts: number; scores: Record<string, number> }>;
  recommendation: { skillId: string; scenarioId: string; scenarioTitle: string; reason: string };
  recommendedDrill: DrillDefinition;
};

export type LearningDashboardResult = { dashboard: LearningDashboard | null; error?: string };

export type CoachSkillId = "interests" | "questions" | "active_listening" | "criteria" | "meso" | "exchanges" | "batna" | "commitments";

export type PrebriefWorksheetInput = {
  focusSkill: CoachSkillId;
  goal: string;
  interests: string[];
  participantBatna: string;
  participantReservation: string;
  plannedQuestions: string[];
};

export type PrebriefWorksheet = PrebriefWorksheetInput & {
  id: string | null;
  sessionId: string;
  saved: boolean;
  inheritedFromAttempt: number | null;
  updatedAt: string | null;
};

export type CoachBudget = { usedTokens: number; remainingTokens: number; usedCalls: number; remainingCalls: number };

export type CoachHint = {
  question: string;
  skillId: CoachSkillId;
  mode: "socratic";
  provider: "gemini" | "deterministic";
  fallback: boolean;
  cached: boolean;
  roleAligned: true;
  officialOutcomeUnchanged: true;
  budget: CoachBudget;
};

export type CoachRewrite = {
  officialMessageId: string;
  originalText: string;
  revisedText: string;
  possibleOpponentReply: string;
  analysis: string;
  impacts: Array<{ skillId: CoachSkillId; title: string; effect: "improved" | "unchanged" | "weakened"; explanation: string }>;
  provider: "gemini" | "deterministic";
  fallback: boolean;
  cached: boolean;
  roleAligned: true;
  officialTranscriptChanged: false;
  officialOutcomeUnchanged: true;
  budget: CoachBudget;
};

export type PersonalizedMiniDrill = {
  id: string;
  sessionId: string;
  skillId: CoachSkillId;
  title: string;
  durationMinutes: number;
  prompt: string;
  sourceTurn: number | null;
  sourceQuote: string | null;
  instructions: string[];
  successChecklist: string[];
  suggestedTemplate: string;
  officialOutcomeUnchanged: true;
};

export type AdaptiveDrillFeedback = {
  drillId: string;
  skillId: CoachSkillId;
  score: number;
  passed: boolean;
  feedback: string;
  checks: Array<{ title: string; met: boolean }>;
  officialOutcomeUnchanged: true;
};

export type AdaptiveCoachSummary = {
  sessionId: string;
  focusSkill: CoachSkillId;
  hintCount: number;
  rewriteCount: number;
  drillCompleted: boolean;
  previousSkillScore: number | null;
  currentSkillScore: number | null;
  skillDelta: number | null;
  officialOutcomeUnchanged: true;
  budget: CoachBudget;
};

export type MotivationDashboard = {
  enabled: boolean;
  teamOptIn: boolean;
  streak: { current: number; longest: number; lastPracticedOn: string | null };
  skillTree: Array<{ id: string; title: string; level: number; unlocked: boolean; unlockReason: string; nextRequirement: string | null }>;
  achievements: Array<{ id: string; title: string; description: string; earnedAt: string }>;
  dailyChallenge: { date: string; scenarioId: string; scenarioTitle: string; seed: number; skillId: string; completed: boolean; sessionId: string | null };
  weeklyChallenge: { weekStart: string; scenarioId: string; scenarioTitle: string; seed: number; skillId: string; completed: boolean; sessionId: string | null };
  team: { id: string; name: string; inviteCode: string; members: number } | null;
  leaderboard: Array<{ rank: number; teamId: string; teamName: string; members: number; points: number; completedSessions: number }>;
};
export type MotivationDashboardResult = { dashboard: MotivationDashboard | null; error?: string };

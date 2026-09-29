const MAX_TURN_LENGTH = 4000;
const NORMAL_QUIET_MS = 1900;
const SHORT_QUIET_MS = 3100;

function words(value: string): string[] {
  return value.match(/[\p{L}\p{N}]+/gu) ?? [];
}

function isGreetingOnly(value: string): boolean {
  const normalized = words(value).join(" ").toLocaleLowerCase("ru");
  return /^(?:добрый день|добрый вечер|доброе утро|здравствуйте|здравствуй|привет|приветствую|алло)(?: уважаемые коллеги)?$/.test(normalized);
}

/** Recognition may stop mid-sentence and start again with a repeated prefix. */
export function combineRecognitionSegments(previous: string, next: string): string {
  const left = previous.trim();
  const right = next.trim();
  if (!left) return right;
  if (!right) return left;
  const leftWords = words(left);
  const rightWords = words(right);
  const limit = Math.min(8, leftWords.length, rightWords.length);
  for (let overlap = limit; overlap >= 2; overlap -= 1) {
    const tail = leftWords.slice(-overlap).map((word) => word.toLocaleLowerCase("ru"));
    const head = rightWords.slice(0, overlap).map((word) => word.toLocaleLowerCase("ru"));
    if (tail.every((word, index) => word === head[index])) {
      return `${left} ${rightWords.slice(overlap).join(" ")}`.trim().slice(0, MAX_TURN_LENGTH);
    }
  }
  return `${left} ${right}`.trim().slice(0, MAX_TURN_LENGTH);
}

/** A final STT segment is not the end of a conversational turn. */
export class CallTurnPolicy {
  private text = "";
  private lastRecognitionAt = 0;
  private lastMicActivityAt = 0;

  get pending(): string { return this.text; }

  updateRecognition(text: string, at: number): void {
    this.text = text.trim().slice(0, MAX_TURN_LENGTH);
    if (this.text) this.lastRecognitionAt = at;
  }

  noteMicActivity(at: number): void {
    if (this.text) this.lastMicActivityAt = at;
  }

  remainingQuietMs(now: number): number | null {
    if (!this.text) return null;
    // A greeting often precedes the actual answer after a natural pause.
    // It remains pending until more speech or the user's explicit send action.
    if (isGreetingOnly(this.text)) return null;
    const quietMs = words(this.text).length <= 3 ? SHORT_QUIET_MS : NORMAL_QUIET_MS;
    return Math.max(0, quietMs - (now - Math.max(this.lastRecognitionAt, this.lastMicActivityAt)));
  }

  takeIfReady(now: number): string | null {
    if (this.remainingQuietMs(now) !== 0) return null;
    return this.takeNow();
  }

  takeNow(): string | null {
    const ready = this.text.trim();
    this.reset();
    return ready || null;
  }

  reset(): void {
    this.text = "";
    this.lastRecognitionAt = 0;
    this.lastMicActivityAt = 0;
  }
}

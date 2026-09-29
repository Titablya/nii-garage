"use client";

import { useEffect, useRef, useState } from "react";
import { openOpeningAudioStream, openOpponentAudioStream } from "../lib/api";
import { CallTurnPolicy, combineRecognitionSegments } from "../lib/call-turn-policy";
import type { ChatMessage, MessageResult } from "../lib/types";

type RecognitionResult = { isFinal: boolean; 0: { transcript: string } };
type RecognitionEvent = Event & { results: { length: number; [index: number]: RecognitionResult } };
type Recognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: Event & { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: (audioTrack?: MediaStreamTrack) => void;
  stop: () => void;
};
type RecognitionConstructor = new () => Recognition;
type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "paused";

const phaseLabels: Record<Phase, string> = {
  idle: "Звонок готов",
  connecting: "Подключаем микрофон…",
  listening: "На связи · слушаю",
  thinking: "Оппонент отвечает · микрофон включён",
  speaking: "Оппонент говорит · можете перебить",
  paused: "Звонок завершён",
};

function recognitionConstructor(): RecognitionConstructor | undefined {
  const browser = window as Window & { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
}

function stripOpponentEcho(recognized: string, opponent: string): string {
  const words = (recognized.match(/[\p{L}\p{N}]+/gu) ?? []).map((word) => word.toLocaleLowerCase("ru"));
  const opponentWords = (opponent.match(/[\p{L}\p{N}]+/gu) ?? []).map((word) => word.toLocaleLowerCase("ru"));
  if (!words.length || !opponentWords.length) return recognized;
  for (let count = Math.min(words.length, opponentWords.length); count > 0; count -= 1) {
    for (let start = 0; start + count <= opponentWords.length; start += 1) {
      let matches = 0;
      for (let index = 0; index < count; index += 1) if (words[index] === opponentWords[start + index]) matches += 1;
      const echoes = count >= 3 ? matches >= count - 1 && matches / count >= 0.65
        : count === 2 ? matches === 2
          : words.length === 1 && matches === 1 && words[0].length >= 7;
      if (echoes) return (recognized.match(/[\p{L}\p{N}]+/gu) ?? []).slice(count).join(" ");
    }
  }
  return recognized;
}

function uncommittedSpeech(raw: string, committed: string): string {
  if (!committed) return raw.trim();
  if (raw.toLocaleLowerCase("ru").startsWith(committed.toLocaleLowerCase("ru"))) return raw.slice(committed.length).trim();
  const words = raw.match(/[\p{L}\p{N}]+/gu) ?? [];
  const previous = committed.match(/[\p{L}\p{N}]+/gu) ?? [];
  let matching = 0;
  while (matching < Math.min(words.length, previous.length) && words[matching].toLocaleLowerCase("ru") === previous[matching].toLocaleLowerCase("ru")) matching += 1;
  if (matching >= Math.min(2, previous.length)) return words.slice(previous.length).join(" ");
  return raw.trim();
}

export function CallConversation({ sessionId, messages, disabled, isTerminal, onTurn, onActiveChange }: {
  sessionId: string | null;
  messages: ChatMessage[];
  disabled: boolean;
  isTerminal: boolean;
  onTurn: (text: string) => Promise<MessageResult | null>;
  onActiveChange: (active: boolean) => void;
}) {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [consentOpen, setConsentOpen] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [pendingSpeech, setPendingSpeech] = useState(false);
  const [notice, setNotice] = useState("");
  const [turnCount, setTurnCount] = useState(0);
  const consentInputRef = useRef<HTMLInputElement | null>(null);
  const activeRef = useRef(false);
  const terminalRef = useRef(isTerminal);
  const busyRef = useRef(false);
  const phaseRef = useRef<Phase>("idle");
  const recognitionRef = useRef<Recognition | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const micMonitorRef = useRef<number | null>(null);
  const soundSourcesRef = useRef(new Set<AudioBufferSourceNode>());
  const audioAbortRef = useRef<AbortController | null>(null);
  const playbackEpochRef = useRef(0);
  const playbackResolveRef = useRef<(() => void) | null>(null);
  const speakingTextRef = useRef("");
  const echoReferenceRef = useRef("");
  const lastSpokenIdRef = useRef("");
  const turnPolicyRef = useRef(new CallTurnPolicy());
  const recognitionBaseRef = useRef("");
  const rawTranscriptRef = useRef("");
  const committedRawRef = useRef("");
  const queuedTextRef = useRef("");
  const silenceTimerRef = useRef<number | null>(null);
  const restartTimerRef = useRef<number | null>(null);
  const restartFailuresRef = useRef(0);
  const recognitionStartedAtRef = useRef(0);
  const echoGuardUntilRef = useRef(0);
  const onTurnRef = useRef(onTurn);
  const onActiveChangeRef = useRef(onActiveChange);
  onTurnRef.current = onTurn;
  onActiveChangeRef.current = onActiveChange;
  terminalRef.current = isTerminal;

  function showPhase(value: Phase) {
    phaseRef.current = value;
    setPhase(value);
  }

  function clearTimers() {
    if (silenceTimerRef.current !== null) window.clearTimeout(silenceTimerRef.current);
    if (restartTimerRef.current !== null) window.clearTimeout(restartTimerRef.current);
    silenceTimerRef.current = null;
    restartTimerRef.current = null;
  }

  function stopMicMonitor() {
    if (micMonitorRef.current !== null) window.clearInterval(micMonitorRef.current);
    micMonitorRef.current = null;
  }

  function startMicMonitor(stream: MediaStream, context: AudioContext) {
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    stopMicMonitor();
    micMonitorRef.current = window.setInterval(() => {
      if (!activeRef.current || (phaseRef.current !== "listening" && phaseRef.current !== "thinking")) return;
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) {
        const amplitude = (sample - 128) / 128;
        sum += amplitude * amplitude;
      }
      if (Math.sqrt(sum / samples.length) > 0.027) turnPolicyRef.current.noteMicActivity(Date.now());
    }, 60);
  }

  function interruptPlayback() {
    playbackEpochRef.current += 1;
    audioAbortRef.current?.abort();
    audioAbortRef.current = null;
    for (const source of soundSourcesRef.current) {
      try { source.stop(); } catch { /* already ended */ }
    }
    soundSourcesRef.current.clear();
    window.speechSynthesis?.cancel();
    playbackResolveRef.current?.();
    playbackResolveRef.current = null;
    speakingTextRef.current = "";
    if (activeRef.current && !busyRef.current) showPhase("listening");
  }

  function stopCall() {
    activeRef.current = false;
    busyRef.current = false;
    queuedTextRef.current = "";
    turnPolicyRef.current.reset();
    recognitionBaseRef.current = "";
    rawTranscriptRef.current = "";
    committedRawRef.current = "";
    echoReferenceRef.current = "";
    setPendingSpeech(false);
    clearTimers();
    stopMicMonitor();
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    try { recognition?.stop(); } catch { /* already stopped */ }
    interruptPlayback();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    showPhase("paused");
    onActiveChangeRef.current(false);
  }

  useEffect(() => {
    setSupported(Boolean(window.isSecureContext && recognitionConstructor() && typeof navigator.mediaDevices?.getUserMedia === "function" && typeof window.AudioContext === "function"));
    return () => {
      activeRef.current = false;
      clearTimers();
      stopMicMonitor();
      try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
      recognitionRef.current = null;
      interruptPlayback();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void audioContextRef.current?.close();
      onActiveChangeRef.current(false);
    };
  }, []);

  useEffect(() => {
    if (isTerminal && activeRef.current) stopCall();
  }, [isTerminal]);

  useEffect(() => {
    if (!consentOpen) return;
    consentInputRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConsentOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [consentOpen]);

  function commitUtterance(text: string) {
    if (!activeRef.current || !text.trim() || terminalRef.current) return;
    const spoken = text.trim().slice(0, 4000);
    if (!spoken) return;
    if (phaseRef.current === "speaking") interruptPlayback();
    setTranscript(spoken);
    if (busyRef.current) {
      queuedTextRef.current = `${queuedTextRef.current} ${spoken}`.trim().slice(0, 4000);
      setNotice("Услышал дополнение. Передам его после текущего ответа.");
      return;
    }
    const next = `${queuedTextRef.current} ${spoken}`.trim().slice(0, 4000);
    queuedTextRef.current = "";
    void sendTurn(next);
  }

  function scheduleTurnCheck() {
    if (silenceTimerRef.current !== null) window.clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = null;
    const remaining = turnPolicyRef.current.remainingQuietMs(Date.now());
    if (remaining === null) return;
    silenceTimerRef.current = window.setTimeout(() => flushUtterance(), Math.max(80, remaining));
  }

  function flushUtterance(force = false) {
    if (!activeRef.current) return;
    if (silenceTimerRef.current !== null) window.clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = null;
    const spoken = force ? turnPolicyRef.current.takeNow() : turnPolicyRef.current.takeIfReady(Date.now());
    if (!spoken) {
      if (turnPolicyRef.current.pending) scheduleTurnCheck();
      return;
    }
    setPendingSpeech(false);
    recognitionBaseRef.current = "";
    committedRawRef.current = rawTranscriptRef.current;
    commitUtterance(spoken);
  }

  function scheduleRecognitionRestart(failed: boolean) {
    if (!activeRef.current || terminalRef.current || restartTimerRef.current !== null) return;
    restartFailuresRef.current = failed ? restartFailuresRef.current + 1 : 0;
    const delay = failed ? Math.min(3000, 250 * 2 ** Math.min(restartFailuresRef.current - 1, 4)) : 120;
    restartTimerRef.current = window.setTimeout(() => {
      restartTimerRef.current = null;
      startRecognition();
    }, delay);
  }

  function startRecognition() {
    if (!activeRef.current || terminalRef.current || recognitionRef.current) return;
    const SpeechRecognition = recognitionConstructor();
    if (!SpeechRecognition) {
      setNotice("Браузер перестал поддерживать распознавание. Можно открыть резервный голосовой режим ниже.");
      stopCall();
      return;
    }
    recognitionBaseRef.current = turnPolicyRef.current.pending;
    rawTranscriptRef.current = "";
    committedRawRef.current = "";
    echoReferenceRef.current = speakingTextRef.current;
    const recognition = new SpeechRecognition();
    recognition.lang = "ru-RU";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognitionRef.current = recognition;
    recognition.onresult = (event) => {
      if (!activeRef.current || recognitionRef.current !== recognition) return;
      let words = "";
      for (let index = 0; index < event.results.length; index += 1) {
        words += `${event.results[index][0].transcript} `;
      }
      const raw = words.trim();
      rawTranscriptRef.current = raw;
      const pending = uncommittedSpeech(raw, committedRawRef.current);
      const checkEcho = phaseRef.current === "speaking" || Date.now() < echoGuardUntilRef.current;
      const heard = (checkEcho ? stripOpponentEcho(pending, echoReferenceRef.current) : pending).trim().slice(0, 4000);
      if (!heard) {
        if (checkEcho) committedRawRef.current = raw;
        return;
      }
      const latestIsFinal = event.results[event.results.length - 1]?.isFinal ?? false;
      if (phaseRef.current === "speaking" && heard.length < 8 && !latestIsFinal) return;
      if (checkEcho && heard !== pending) {
        const remainingWords = heard.match(/[\p{L}\p{N}]+/gu)?.length ?? 0;
        const rawWords = raw.match(/[\p{L}\p{N}]+/gu) ?? [];
        committedRawRef.current = rawWords.slice(0, Math.max(0, rawWords.length - remainingWords)).join(" ");
      }
      if (phaseRef.current === "speaking") interruptPlayback();
      const combined = combineRecognitionSegments(recognitionBaseRef.current, heard);
      turnPolicyRef.current.updateRecognition(combined, Date.now());
      setTranscript(combined);
      setPendingSpeech(true);
      restartFailuresRef.current = 0;
      scheduleTurnCheck();
    };
    recognition.onerror = (event) => {
      if (!activeRef.current) return;
      if (event.error === "no-speech" || event.error === "aborted") return;
      if (event.error === "not-allowed" || event.error === "service-not-allowed" || event.error === "audio-capture") {
        setNotice("Браузер закрыл доступ к микрофону. Разрешите его снова или откройте резервный голосовой режим.");
        stopCall();
        return;
      }
      setNotice("Распознавание временно прервалось. Восстанавливаю связь автоматически…");
      recognitionRef.current = null;
      try { recognition.stop(); } catch { /* browser already stopped */ }
      scheduleRecognitionRestart(true);
    };
    recognition.onend = () => {
      if (recognitionRef.current !== recognition || !activeRef.current) return;
      recognitionRef.current = null;
      // Browser STT may end between two clauses; its lifecycle is not a turn boundary.
      if (turnPolicyRef.current.pending) scheduleTurnCheck();
      if (phaseRef.current !== "speaking") showPhase(busyRef.current ? "thinking" : "listening");
      scheduleRecognitionRestart(Date.now() - recognitionStartedAtRef.current < 1000);
    };
    try {
      const audioTrack = streamRef.current?.getAudioTracks()[0];
      try { recognition.start(audioTrack); }
      catch (error) {
        if (!audioTrack) throw error;
        recognition.start();
      }
      recognitionStartedAtRef.current = Date.now();
      if (!busyRef.current && phaseRef.current !== "speaking") showPhase("listening");
    } catch {
      recognitionRef.current = null;
      setNotice("Переподключаю распознавание речи…");
      scheduleRecognitionRestart(true);
    }
  }

  async function playMessage(message: ChatMessage): Promise<void> {
    if (!activeRef.current) return;
    const epoch = playbackEpochRef.current;
    speakingTextRef.current = message.text;
    echoReferenceRef.current = message.text;
    showPhase("speaking");
    if (!sessionId) {
      setNotice("Натуральный голос доступен после подключения к серверу. Можно открыть резервный голосовой режим.");
    } else {
      const abort = new AbortController();
      audioAbortRef.current = abort;
      const result = message.id.endsWith("-opener")
        ? await openOpeningAudioStream(sessionId, abort.signal)
        : await openOpponentAudioStream(sessionId, message.id, abort.signal);
      if (!activeRef.current || epoch !== playbackEpochRef.current) return;
      if (!result.response?.body) {
        setNotice("Натуральный голос временно недоступен. Текст ответа виден в диалоге; звонок остаётся активным.");
      } else {
        const context = audioContextRef.current;
        if (!context) return;
        const reader = result.response.body.getReader();
        let nextAt = context.currentTime + 0.08;
        let carry: number | null = null;
        let received = false;
        try {
          while (activeRef.current && epoch === playbackEpochRef.current) {
            const { value, done } = await reader.read();
            if (done) break;
            if (!value?.length) continue;
            let bytes = value;
            if (carry !== null) {
              const merged = new Uint8Array(bytes.length + 1);
              merged[0] = carry;
              merged.set(bytes, 1);
              bytes = merged;
              carry = null;
            }
            if (bytes.length % 2) {
              carry = bytes[bytes.length - 1];
              bytes = bytes.subarray(0, -1);
            }
            if (!bytes.length) continue;
            received = true;
            const samples = bytes.length / 2;
            const buffer = context.createBuffer(1, samples, 24000);
            const channel = buffer.getChannelData(0);
            const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
            for (let index = 0; index < samples; index += 1) channel[index] = view.getInt16(index * 2, true) / 32768;
            const source = context.createBufferSource();
            source.buffer = buffer;
            source.connect(context.destination);
            source.onended = () => soundSourcesRef.current.delete(source);
            soundSourcesRef.current.add(source);
            nextAt = Math.max(nextAt, context.currentTime + 0.04);
            source.start(nextAt);
            nextAt += samples / 24000;
          }
          if (activeRef.current && epoch === playbackEpochRef.current && received) {
            await new Promise<void>((resolve) => {
              playbackResolveRef.current = resolve;
              window.setTimeout(resolve, Math.max(0, (nextAt - context.currentTime) * 1000 + 40));
            });
            playbackResolveRef.current = null;
          }
        } catch {
          if (activeRef.current && epoch === playbackEpochRef.current) {
            setNotice(received ? "Голосовой поток прервался; продолжайте разговор." : "Натуральный голос временно недоступен. Текст ответа виден в диалоге.");
          }
        } finally {
          reader.releaseLock();
          if (audioAbortRef.current === abort) audioAbortRef.current = null;
        }
      }
    }
    if (activeRef.current && epoch === playbackEpochRef.current) {
      lastSpokenIdRef.current = message.id;
      speakingTextRef.current = "";
      echoGuardUntilRef.current = Date.now() + 400;
      if (!busyRef.current) showPhase("listening");
    }
  }

  async function sendTurn(text: string): Promise<void> {
    if (!activeRef.current || terminalRef.current) return;
    busyRef.current = true;
    showPhase("thinking");
    setTurnCount((count) => count + 1);
    setNotice("");
    let result: MessageResult | null;
    try { result = await onTurnRef.current(text); }
    catch { result = null; }
    if (!activeRef.current) return;
    busyRef.current = false;
    if (!result || result.error) {
      setNotice("Не удалось получить ответ. Звонок остаётся активным — повторите реплику или проверьте диалог.");
      showPhase("listening");
      return;
    }
    if (result.sessionStatus && result.sessionStatus !== "active") {
      setNotice("Переговоры завершены. Откройте разбор диалога.");
      stopCall();
      return;
    }
    const replies = result.replies?.filter((item) => item.author === "opponent")
      ?? (result.reply ? [{ id: "", author: "opponent" as const, text: result.reply, timestamp: "сейчас" }] : []);
    const replyEpoch = playbackEpochRef.current;
    for (const reply of replies) {
      if (!activeRef.current || replyEpoch !== playbackEpochRef.current) return;
      await playMessage(reply);
    }
    if (!activeRef.current || replyEpoch !== playbackEpochRef.current) return;
    const queued = queuedTextRef.current.trim();
    queuedTextRef.current = "";
    if (queued) { window.setTimeout(() => { if (activeRef.current) void sendTurn(queued); }, 50); return; }
    if (activeRef.current && phaseRef.current !== "speaking") showPhase("listening");
  }

  async function startCall() {
    if (activeRef.current || disabled || isTerminal) return;
    activeRef.current = true;
    showPhase("connecting");
    setNotice("");
    try {
      const context = new AudioContext();
      audioContextRef.current = context;
      void context.resume();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
      if (!activeRef.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      streamRef.current = stream;
      startMicMonitor(stream, context);
      onActiveChangeRef.current(true);
      startRecognition();
      const latest = [...messages].reverse().find((item) => item.author === "opponent");
      if (latest && latest.id !== lastSpokenIdRef.current) void playMessage(latest);
    } catch {
      setNotice("Не удалось подключить микрофон. Проверьте разрешение браузера и попробуйте снова.");
      stopCall();
    }
  }

  const active = phase !== "idle" && phase !== "paused";
  return <>
    <section className={`call-conversation ${active ? "active" : ""}`} aria-label="Голосовой звонок">
      <div className="call-heading"><div><span className="card-topline">ПОСТОЯННАЯ СВЯЗЬ</span><h2>Звонок с оппонентом</h2><p>Микрофон остаётся активным, пока идёт звонок. Можно делать паузы внутри фразы: оппонент дождётся окончания вашей мысли.</p></div><span className="call-state" data-phase={phase}><i aria-hidden="true" />{phaseLabels[phase]}</span></div>
      <div className="call-controls">
        {!active ? <button className="button primary" type="button" disabled={disabled || supported === false} onClick={() => setConsentOpen(true)}>Начать звонок</button> : <button className="button ghost" type="button" onClick={stopCall}>Завершить звонок</button>}
        {phase === "speaking" && <button className="button secondary" type="button" onClick={() => { interruptPlayback(); setNotice("Оппонент остановлен. Говорите — микрофон уже включён."); }}>Перебить</button>}
        {pendingSpeech && active && phase !== "speaking" && <button className="button secondary" type="button" onClick={() => flushUtterance(true)}>Я закончил — ответить</button>}
        {turnCount > 0 && <span>{turnCount} {turnCount === 1 ? "ваша реплика" : "ваших реплик"}</span>}
      </div>
      {transcript && <div className="call-transcript"><span>{pendingSpeech ? "СЛУШАЮ · МОЖНО ПРОДОЛЖИТЬ" : "ПОСЛЕДНЯЯ РАСПОЗНАННАЯ РЕПЛИКА"}</span><p>{transcript}</p></div>}
      {notice && <p className="call-notice" role="status">{notice}</p>}
      <small>{supported === false ? "Нужны Chrome или Edge, HTTPS и доступ к микрофону. Резервный голосовой режим доступен ниже." : "Для надёжного перебивания используйте наушники. Наш сервер сохраняет только текст реплик, а не исходное аудио."}</small>
    </section>
    {consentOpen && <div className="modal-backdrop" role="presentation"><section className="voice-consent" role="dialog" aria-modal="true" aria-labelledby="call-consent-title"><span className="card-topline">Голосовой звонок</span><h2 id="call-consent-title">Начать постоянную голосовую связь?</h2><p>Микрофон будет активен до завершения звонка, в том числе пока говорит оппонент. Браузер может передавать звук своему сервису распознавания. Наш сервер получит и сохранит только текст; реплика отправится после устойчивой паузы, а короткое приветствие система не сочтёт завершённым ответом сразу.</p><label className="consent-check"><input ref={consentInputRef} type="checkbox" checked={consentChecked} onChange={(event) => setConsentChecked(event.target.checked)} /><span>Я согласен на постоянное распознавание и автоматическую отправку моих реплик в этой тренировке.</span></label><div className="voice-consent-actions"><button className="button ghost" type="button" onClick={() => setConsentOpen(false)}>Отмена</button><button className="button primary" type="button" disabled={!consentChecked} onClick={() => { setConsentOpen(false); void startCall(); }}>Подключить микрофон</button></div><small>Разговор можно остановить в любой момент. Для проверки текста до отправки используйте резервный режим.</small></section></div>}
  </>;
}

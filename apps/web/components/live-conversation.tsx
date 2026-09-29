"use client";

import { useEffect, useRef, useState } from "react";
import { getOpponentAudio } from "../lib/api";
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
  start: () => void;
  stop: () => void;
};
type RecognitionConstructor = new () => Recognition;
type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "paused";

function recognitionConstructor(): RecognitionConstructor | undefined {
  const browser = window as Window & { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
}

const phaseLabels: Record<Phase, string> = {
  idle: "Готов к разговору",
  connecting: "Подключаем микрофон…",
  listening: "Слушаю вас",
  thinking: "Оппонент готовит ответ…",
  speaking: "Оппонент говорит",
  paused: "Разговор остановлен",
};

export function LiveConversation({ sessionId, messages, disabled, isTerminal, onTurn, onActiveChange }: {
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
  const [notice, setNotice] = useState("");
  const [turnCount, setTurnCount] = useState(0);
  const consentInputRef = useRef<HTMLInputElement | null>(null);
  const activeRef = useRef(false);
  const phaseRef = useRef<Phase>("idle");
  const recognitionRef = useRef<Recognition | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserFrameRef = useRef<number | null>(null);
  const lastSpeechAtRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const silenceTimerRef = useRef<number | null>(null);
  const restartTimerRef = useRef<number | null>(null);
  const turnLimitRef = useRef<number | null>(null);
  const transcriptRef = useRef("");
  const stopRequestedRef = useRef(false);
  const playbackTokenRef = useRef(0);
  const lastSpokenIdRef = useRef("");
  const playbackResolveRef = useRef<(() => void) | null>(null);
  const onTurnRef = useRef(onTurn);
  const onActiveChangeRef = useRef(onActiveChange);
  const terminalRef = useRef(isTerminal);
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
    if (turnLimitRef.current !== null) window.clearTimeout(turnLimitRef.current);
    silenceTimerRef.current = null;
    restartTimerRef.current = null;
    turnLimitRef.current = null;
  }

  function stopSoundAnalysis() {
    if (analyserFrameRef.current !== null) window.cancelAnimationFrame(analyserFrameRef.current);
    analyserFrameRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
  }

  function stopPlayback() {
    playbackTokenRef.current += 1;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    window.speechSynthesis?.cancel();
    playbackResolveRef.current?.();
    playbackResolveRef.current = null;
  }

  function stopConversation(nextPhase: Phase = "paused") {
    activeRef.current = false;
    clearTimers();
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    stopPlayback();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    stopSoundAnalysis();
    showPhase(nextPhase);
    onActiveChangeRef.current(false);
  }

  function finishUtterance(recognition: Recognition) {
    if (recognitionRef.current !== recognition || stopRequestedRef.current) return;
    stopRequestedRef.current = true;
    try { recognition.stop(); } catch { stopRequestedRef.current = false; }
  }

  useEffect(() => {
    setSupported(Boolean(window.isSecureContext && recognitionConstructor() && navigator.mediaDevices?.getUserMedia));
    return () => {
      activeRef.current = false;
      clearTimers();
      recognitionRef.current?.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      stopSoundAnalysis();
      stopPlayback();
      onActiveChangeRef.current(false);
    };
  }, []);

  useEffect(() => {
    if (isTerminal && activeRef.current) stopConversation();
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

  function startListening() {
    if (!activeRef.current || terminalRef.current) return;
    const SpeechRecognition = recognitionConstructor();
    if (!SpeechRecognition) { setNotice("Распознавание речи недоступно. Продолжите текстом."); stopConversation(); return; }
    clearTimers();
    transcriptRef.current = "";
    stopRequestedRef.current = false;
    lastSpeechAtRef.current = 0;
    setTranscript("");
    showPhase("listening");
    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "ru-RU";
    recognitionRef.current = recognition;
    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) finalText += `${result[0].transcript} `;
        else interimText += result[0].transcript;
      }
      const spoken = `${finalText}${interimText}`.trim().slice(0, 4000);
      transcriptRef.current = spoken;
      setTranscript(spoken);
      if (silenceTimerRef.current !== null) window.clearTimeout(silenceTimerRef.current);
      if (spoken) {
        silenceTimerRef.current = window.setTimeout(() => {
          if (activeRef.current) finishUtterance(recognition);
        }, 1700);
      }
    };
    recognition.onerror = (event) => {
      if (!activeRef.current) return;
      if (event.error === "no-speech" || event.error === "aborted") return;
      setNotice(`Распознавание остановилось${event.error ? ` (${event.error})` : ""}. Расшифровка осталась на экране — можно повторить или перейти к тексту.`);
      stopConversation();
    };
    recognition.onend = () => {
      if (recognitionRef.current !== recognition || !activeRef.current) return;
      recognitionRef.current = null;
      clearTimers();
      const spoken = transcriptRef.current.trim();
      if (spoken) { void submitTurn(spoken); return; }
      restartTimerRef.current = window.setTimeout(startListening, 300);
    };
    try {
      recognition.start();
      turnLimitRef.current = window.setTimeout(() => {
        finishUtterance(recognition);
      }, 120000);
    } catch {
      setNotice("Не удалось запустить распознавание. Проверьте доступ к микрофону и повторите.");
      stopConversation();
    }
  }

  async function speakWithBrowser(text: string, token: number): Promise<boolean> {
    if (!window.speechSynthesis || !activeRef.current || token !== playbackTokenRef.current) return false;
    return new Promise((resolve) => {
      playbackResolveRef.current = () => resolve(false);
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "ru-RU";
      utterance.rate = 1;
      const russianVoice = window.speechSynthesis.getVoices().find((voice) => voice.lang.toLowerCase().startsWith("ru"));
      if (russianVoice) utterance.voice = russianVoice;
      utterance.onend = () => { playbackResolveRef.current = null; resolve(true); };
      utterance.onerror = () => { playbackResolveRef.current = null; resolve(false); };
      window.speechSynthesis.speak(utterance);
    });
  }

  async function speakReply(message: ChatMessage, token: number): Promise<void> {
    if (!activeRef.current || token !== playbackTokenRef.current) return;
    showPhase("speaking");
    if (sessionId && !message.id.endsWith("-opener")) {
      const result = await getOpponentAudio(sessionId, message.id);
      if (!activeRef.current || token !== playbackTokenRef.current) return;
      if (result.audio) {
        const audioUrl = URL.createObjectURL(result.audio);
        audioUrlRef.current = audioUrl;
        const audio = new Audio(audioUrl);
        audioRef.current = audio;
        try {
          await new Promise<void>((resolve, reject) => {
            playbackResolveRef.current = resolve;
            audio.onended = () => { playbackResolveRef.current = null; resolve(); };
            audio.onerror = () => { playbackResolveRef.current = null; reject(new Error("audio playback failed")); };
            void audio.play().catch(reject);
          });
          if (token === playbackTokenRef.current) lastSpokenIdRef.current = message.id;
          return;
        } catch {
          // The browser's speech engine can still read the committed text.
        } finally {
          playbackResolveRef.current = null;
          audioRef.current = null;
          URL.revokeObjectURL(audioUrl);
          if (audioUrlRef.current === audioUrl) audioUrlRef.current = null;
        }
      }
    }
    if (activeRef.current && token === playbackTokenRef.current) {
      if (!message.id.endsWith("-opener")) setNotice("Естественный голос временно недоступен; ответ читает браузер.");
      const spoken = await speakWithBrowser(message.text, token);
      if (spoken && token === playbackTokenRef.current) lastSpokenIdRef.current = message.id;
      if (!spoken && activeRef.current && token === playbackTokenRef.current) {
        setNotice("Браузер не смог воспроизвести голос. Прочитайте ответ в диалоге и нажмите «Начать разговор», чтобы продолжить.");
        stopConversation();
      }
    }
  }

  async function submitTurn(text: string) {
    if (!activeRef.current || phaseRef.current !== "listening") return;
    showPhase("thinking");
    setTurnCount((count) => count + 1);
    const result = await onTurnRef.current(text);
    if (!activeRef.current) return;
    if (!result || result.error) {
      setNotice("Ответ не получен. Ваша фраза осталась в диалоге; воспользуйтесь кнопкой «Повторить» или продолжите текстом.");
      stopConversation();
      return;
    }
    const replies = result.replies?.filter((item) => item.author === "opponent")
      ?? (result.reply ? [{ id: "", author: "opponent" as const, text: result.reply, timestamp: "сейчас" }] : []);
    const token = playbackTokenRef.current;
    for (const reply of replies) {
      if (!activeRef.current || token !== playbackTokenRef.current) return;
      await speakReply(reply, token);
    }
    if (!activeRef.current || token !== playbackTokenRef.current) return;
    if (result.sessionStatus && result.sessionStatus !== "active") {
      setNotice("Переговоры завершены. Откройте разбор диалога.");
      stopConversation();
      return;
    }
    startListening();
  }

  async function startConversation() {
    if (activeRef.current || disabled || isTerminal) return;
    activeRef.current = true;
    showPhase("connecting");
    setNotice("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      if (!activeRef.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      streamRef.current = stream;
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      const levels = new Uint8Array(analyser.fftSize);
      const sampleLevel = () => {
        if (!activeRef.current) return;
        if (phaseRef.current === "listening") {
          analyser.getByteTimeDomainData(levels);
          let sum = 0;
          for (const level of levels) { const amplitude = (level - 128) / 128; sum += amplitude * amplitude; }
          const now = performance.now();
          if (Math.sqrt(sum / levels.length) > 0.035) lastSpeechAtRef.current = now;
          if (lastSpeechAtRef.current > 0 && transcriptRef.current.trim() && now - lastSpeechAtRef.current > 1700 && recognitionRef.current) finishUtterance(recognitionRef.current);
        }
        analyserFrameRef.current = window.requestAnimationFrame(sampleLevel);
      };
      sampleLevel();
      onActiveChangeRef.current(true);
      const latestOpponent = [...messages].reverse().find((item) => item.author === "opponent");
      if (latestOpponent && latestOpponent.id !== lastSpokenIdRef.current) {
        const token = playbackTokenRef.current;
        await speakReply(latestOpponent, token);
        if (activeRef.current && token === playbackTokenRef.current) startListening();
      } else startListening();
    } catch {
      setNotice("Не удалось получить доступ к микрофону. Проверьте разрешение браузера и попробуйте снова.");
      stopConversation();
    }
  }

  function interrupt() {
    if (!activeRef.current || phaseRef.current !== "speaking") return;
    stopPlayback();
    setNotice("Оппонент остановлен. Говорите — после паузы фраза отправится автоматически.");
    startListening();
  }

  const active = phase === "connecting" || phase === "listening" || phase === "thinking" || phase === "speaking";
  return <>
    <section className={`live-conversation ${active ? "active" : ""}`} aria-label="Живой голосовой разговор">
      <div className="live-conversation-heading"><div><span className="card-topline">НОВЫЙ РЕЖИМ</span><h2>Живой разговор</h2><p>Вы говорите — оппонент отвечает естественным голосом. После короткой паузы реплика отправляется сама.</p></div><span className="live-conversation-state" data-phase={phase}><i aria-hidden="true" />{phaseLabels[phase]}</span></div>
      <div className="live-conversation-controls">
        {!active ? <button className="button primary" type="button" disabled={disabled || supported === false} onClick={() => setConsentOpen(true)}>Начать разговор</button> : <button className="button ghost" type="button" onClick={() => stopConversation()}>Остановить разговор</button>}
        {phase === "speaking" && <button className="button secondary" type="button" onClick={interrupt}>Перебить оппонента</button>}
        {turnCount > 0 && <span>{turnCount} {turnCount === 1 ? "ваша реплика" : "ваших реплик"}</span>}
      </div>
      {transcript && <div className="live-conversation-transcript"><span>{phase === "listening" ? "Распознаём вашу речь" : "Последняя реплика"}</span><p>{transcript}</p></div>}
      {notice && <p className="live-conversation-notice" role="status">{notice}</p>}
      <small>{supported === false ? "Для разговора нужны Chrome или Edge и HTTPS. Текстовый режим доступен ниже." : "Используйте наушники, чтобы звук оппонента не попадал в микрофон. Наш сервер не сохраняет аудио вашей речи; текст входит в протокол переговоров."}</small>
    </section>
    {consentOpen && <div className="modal-backdrop" role="presentation"><section className="voice-consent" role="dialog" aria-modal="true" aria-labelledby="live-consent-title"><span className="card-topline">Голосовой разговор</span><h2 id="live-consent-title">Начать переговоры голосом?</h2><p>Браузер получит доступ к микрофону и распознает речь. Поставщик браузера может обрабатывать аудио для распознавания; наш сервер его не сохраняет. После паузы около 1,7 секунды текст автоматически попадёт в диалог, и AI-оппонент ответит голосом.</p><label className="consent-check"><input ref={consentInputRef} type="checkbox" checked={consentChecked} onChange={(event) => setConsentChecked(event.target.checked)} /><span>Я согласен на распознавание и автоматическую отправку моих устных реплик в этой тренировке.</span></label><div className="voice-consent-actions"><button className="button ghost" type="button" onClick={() => setConsentOpen(false)}>Отмена</button><button className="button primary" type="button" disabled={!consentChecked} onClick={() => { setConsentOpen(false); void startConversation(); }}>Разрешить микрофон</button></div><small>Разговор можно остановить в любой момент. Для проверки текста до отправки используйте режим диктовки.</small></section></div>}
  </>;
}

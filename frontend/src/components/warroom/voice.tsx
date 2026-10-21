import { useCallback, useEffect, useRef, useState } from "react";
import { AnamAvatar, InterviewerAvatar, useBrowserTts, type AnamHandle } from "../voice";
import { apiUrl } from "../../lib/api";

const VOICE_STORAGE_KEY = "wr_voice_enabled";

function readInitialVoiceEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(VOICE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export type Voice = ReturnType<typeof useArchitectVoice>;

/** Голосовое сопровождение ИИ-архитектора (по умолчанию выключено; включается только переключателем «Озвучивать разбор»). */
export function useArchitectVoice() {
  const anamRef = useRef<AnamHandle | null>(null);
  const [videoOn, setVideoOn] = useState(false);
  const [voiceEnabled, setVoiceEnabledState] = useState<boolean>(readInitialVoiceEnabled);
  const [speaking, setSpeaking] = useState(false);
  const [subtitle, setSubtitle] = useState("");
  const [channel, setChannel] = useState<"anam" | "mp3" | "browser" | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const t0 = useRef(0);
  const voiceEnabledRef = useRef(voiceEnabled);
  voiceEnabledRef.current = voiceEnabled;
  const videoRef = useRef(videoOn);
  videoRef.current = videoOn;
  const { speak: ttsSpeak, stop: ttsStop } = useBrowserTts();

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    anamRef.current?.stop();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    ttsStop();
    setSpeaking(false);
  }, [ttsStop]);

  useEffect(() => () => stop(), [stop]);

  const setVoiceEnabled = useCallback(
    (next: boolean) => {
      voiceEnabledRef.current = next;
      setVoiceEnabledState(next);
      try {
        window.localStorage.setItem(VOICE_STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      if (!next) {
        stop();
      }
    },
    [stop]
  );

  const setMuted = useCallback(
    (m: boolean) => {
      setVoiceEnabled(!m);
    },
    [setVoiceEnabled]
  );

  const fetchAudio = async (
    text: string,
    format: "mp3" | "pcm",
    signal: AbortSignal
  ): Promise<ArrayBuffer | null> => {
    try {
      const r = await fetch(apiUrl("/interview/concierge/speech"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, format }),
        signal,
      });
      if (!r.ok) return null;
      const buf = await r.arrayBuffer();
      return buf.byteLength > 100 ? buf : null;
    } catch {
      return null;
    }
  };

  const speak = useCallback(
    async (text: string) => {
      stop();
      const clean = text.trim().slice(0, 990);
      setSubtitle(clean);
      // Речь звучит только при явно включённом переключателе «Озвучивать разбор»
      if (!clean || !voiceEnabledRef.current) return;
      const ac = new AbortController();
      abortRef.current = ac;
      setSpeaking(true);
      t0.current = performance.now();
      try {
        if (videoRef.current && anamRef.current) {
          const [pcm, ready] = await Promise.all([
            fetchAudio(clean, "pcm", ac.signal),
            anamRef.current.waitReady
              ? anamRef.current.waitReady(4200)
              : Promise.resolve(anamRef.current.live()),
          ]);
          if (ac.signal.aborted) return;
          if (ready && pcm && anamRef.current?.live()) {
            setChannel("anam");
            await anamRef.current.speak(pcm.slice(0));
            return;
          }
        }
        const mp3 = await fetchAudio(clean, "mp3", ac.signal);
        if (ac.signal.aborted) return;
        if (mp3) {
          setChannel("mp3");
          const url = URL.createObjectURL(new Blob([mp3], { type: "audio/mpeg" }));
          await new Promise<void>((resolve) => {
            const a = new Audio(url);
            audioRef.current = a;
            const done = () => {
              URL.revokeObjectURL(url);
              if (audioRef.current === a) audioRef.current = null;
              resolve();
            };
            a.onended = done;
            a.onerror = done;
            ac.signal.addEventListener("abort", done);
            a.play().catch(done);
          });
          return;
        }
        setChannel("browser");
        await new Promise<void>((resolve) => {
          ac.signal.addEventListener("abort", () => resolve());
          if (!ttsSpeak(clean, { onEnd: resolve })) resolve();
        });
      } catch {
        /* прервано */
      } finally {
        if (abortRef.current === ac) {
          abortRef.current = null;
          setSpeaking(false);
        }
      }
    },
    [stop, ttsSpeak]
  );

  const level = useCallback(() => {
    if (!speaking) return 0;
    const t = (performance.now() - t0.current) / 1000;
    return 0.3 + 0.4 * Math.abs(Math.sin(t * 7.7)) * Math.abs(Math.sin(t * 2.3));
  }, [speaking]);

  return {
    anamRef,
    videoOn,
    setVideoOn,
    voiceEnabled,
    setVoiceEnabled,
    muted: !voiceEnabled,
    setMuted,
    speaking,
    subtitle,
    setSubtitle,
    channel,
    speak,
    stop,
    level,
  };
}

export function VoiceControlStrip({ voice }: { voice: Voice }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={voice.voiceEnabled}
        onClick={() => voice.setVoiceEnabled(!voice.voiceEnabled)}
        data-testid="wr-voice-toggle"
        className={`inline-flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-bold transition ${
          voice.voiceEnabled
            ? "border-emerald-400/60 bg-emerald-500/20 text-emerald-100"
            : "border-white/20 bg-white/[0.04] text-white/80 hover:bg-white/10"
        }`}
      >
        <span
          className={`relative h-4 w-7 shrink-0 rounded-full transition ${
            voice.voiceEnabled ? "bg-emerald-400" : "bg-white/25"
          }`}
        >
          <span
            className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
              voice.voiceEnabled ? "left-3.5" : "left-0.5"
            }`}
          />
        </span>
        <span>Озвучивать разбор</span>
      </button>
      {voice.speaking && (
        <button
          type="button"
          onClick={() => voice.stop()}
          data-testid="wr-voice-stop"
          className="rounded-xl border border-rose-400/60 bg-rose-500/25 px-3 py-1.5 text-xs font-extrabold text-rose-100 hover:bg-rose-500/40"
        >
          Остановить голос
        </button>
      )}
    </div>
  );
}

export function AvatarStage({
  voice,
  name,
  role,
  size = 150,
  compact = false,
}: {
  voice: Voice;
  name: string;
  role: string;
  size?: number;
  compact?: boolean;
}) {
  const state = voice.speaking ? "speaking" : "listening";
  const chan =
    voice.channel === "anam"
      ? "живое видео · синхронизация губ"
      : voice.channel === "mp3"
        ? "голос · портрет"
        : voice.channel === "browser"
          ? "голос браузера · портрет"
          : voice.voiceEnabled
            ? "озвучка включена"
            : "озвучка выключена";
  return (
    <div
      className={`flex ${compact ? "flex-row items-center gap-4" : "flex-col items-center gap-3 text-center"}`}
      data-testid="wr-avatar"
    >
      <div
        className="relative shrink-0 overflow-hidden rounded-2xl border border-white/15 bg-black shadow-[0_0_40px_-8px_rgba(99,91,255,0.7)]"
        style={{ width: size, height: size }}
      >
        {voice.videoOn ? (
          <AnamAvatar
            ref={voice.anamRef}
            sessionId="warroom-architect"
            tokenPath="/interview/concierge/avatar-token"
            state={state}
            level={voice.level}
            name={name}
            size={size}
            tone="dark"
            className="[&>figcaption]:hidden"
          />
        ) : (
          <InterviewerAvatar
            state={state}
            level={voice.level}
            name={name}
            size={size}
            tone="dark"
            className="[&>figcaption]:hidden"
          />
        )}
        <span
          className={`absolute left-2 top-2 flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
            voice.speaking ? "bg-emerald-500/90 text-black" : "bg-black/60 text-white/80"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              voice.speaking ? "animate-pulse bg-black" : "bg-emerald-400"
            }`}
          />
          {voice.speaking ? "говорит" : "на связи"}
        </span>
      </div>
      <div className={`min-w-0 ${compact ? "flex-1" : ""}`}>
        <p className="text-sm font-bold text-white">{name}</p>
        <p className="text-[11px] uppercase tracking-wider text-indigo-300/80">
          {role} · {chan}
        </p>
        <p
          className="mt-2 min-h-[3.5rem] text-xs leading-relaxed text-white/80"
          aria-live="polite"
        >
          {voice.subtitle ||
            "Выберите инцидент, включите меры, поправьте код и нажмите «Проверить решение» — здесь появится текстовый разбор."}
        </p>
        <div className={`mt-2 flex flex-wrap gap-2 ${compact ? "" : "justify-center"}`}>
          {!voice.videoOn && (
            <button
              type="button"
              onClick={() => {
                voice.setVoiceEnabled(true);
                voice.setVideoOn(true);
              }}
              className="rounded-lg bg-indigo-500 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-400"
              data-testid="wr-video-on"
            >
              Включить видеоаватар
            </button>
          )}
          <button
            type="button"
            onClick={() => voice.setVoiceEnabled(!voice.voiceEnabled)}
            className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold text-white/80 hover:bg-white/10"
          >
            {voice.voiceEnabled ? "Выключить озвучку" : "Озвучивать разбор"}
          </button>
          {voice.speaking && (
            <button
              type="button"
              onClick={() => voice.stop()}
              className="rounded-lg bg-rose-500/30 px-3 py-1.5 text-xs font-bold text-rose-100 hover:bg-rose-500/50"
            >
              Остановить голос
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

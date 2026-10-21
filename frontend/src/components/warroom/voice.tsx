import { useCallback, useEffect, useRef, useState } from "react";
import { AnamAvatar, InterviewerAvatar, useBrowserTts, type AnamHandle } from "../voice";
import { apiUrl } from "../../lib/api";

export type Voice = ReturnType<typeof useArchitectVoice>;

/** Голосовое сопровождение ИИ-архитектора (использует существующие компоненты voice без их модификации). */
export function useArchitectVoice() {
  const anamRef = useRef<AnamHandle | null>(null);
  const [videoOn, setVideoOn] = useState(false);
  const [muted, setMuted] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [subtitle, setSubtitle] = useState("");
  const [channel, setChannel] = useState<"anam" | "mp3" | "browser" | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const t0 = useRef(0);
  const mutedRef = useRef(muted);
  mutedRef.current = muted;
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

  const fetchAudio = async (text: string, format: "mp3" | "pcm", signal: AbortSignal): Promise<ArrayBuffer | null> => {
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
      if (!clean || mutedRef.current) return;
      const ac = new AbortController();
      abortRef.current = ac;
      setSpeaking(true);
      t0.current = performance.now();
      try {
        if (videoRef.current && anamRef.current) {
          const [pcm, ready] = await Promise.all([
            fetchAudio(clean, "pcm", ac.signal),
            anamRef.current.waitReady ? anamRef.current.waitReady(4200) : Promise.resolve(anamRef.current.live()),
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
    muted,
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
          : "готова к разбору";
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
          <span className={`h-1.5 w-1.5 rounded-full ${voice.speaking ? "animate-pulse bg-black" : "bg-emerald-400"}`} />
          {voice.speaking ? "говорит" : "на связи"}
        </span>
      </div>
      <div className={`min-w-0 ${compact ? "flex-1" : ""}`}>
        <p className="text-sm font-bold text-white">{name}</p>
        <p className="text-[11px] uppercase tracking-wider text-indigo-300/80">
          {role} · {chan}
        </p>
        <p className="mt-2 min-h-[3.5rem] text-xs leading-relaxed text-white/80" aria-live="polite">
          {voice.subtitle ||
            "Выберите инцидент, настройте параметры мер, исправьте код и напишите обоснование — я разберу ваше решение."}
        </p>
        <div className={`mt-2 flex flex-wrap gap-2 ${compact ? "" : "justify-center"}`}>
          {!voice.videoOn && (
            <button
              type="button"
              onClick={() => {
                voice.setMuted(false);
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
            onClick={() => {
              if (!voice.muted) voice.stop();
              voice.setMuted(!voice.muted);
            }}
            className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold text-white/80 hover:bg-white/10"
          >
            {voice.muted ? "Включить звук" : "Без звука"}
          </button>
        </div>
      </div>
    </div>
  );
}

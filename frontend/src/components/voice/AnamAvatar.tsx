// Живой аватар на экране разговора — поставщик Anam (официальный JS SDK), лицо — ТОЛЬКО наше: сгенерированный портрет
// несуществующего человека (frontend/public/avatar/PROVENANCE.md), загруженный в Anam как собственный аватар (ANAM_AVATAR_ID).
// Режим передачи звука: реплики ведущей озвучивает наш синтез (ElevenLabs, женский голос; /speech?format=pcm — pcm_s16le
// 16 кГц моно), Anam только рисует лицо и движение губ; её LLM, голос и микрофон не используются (disableInputAudio).
// Включается флагом движка INTERVIEW_ANAM_ENABLED (по умолчанию выкл.: conversation.channels.avatar=false — компонент
// не монтируется). Любой сбой (503 токена, нет WebRTC, разрыв, таймаут) — тихий откат на свой портрет и голос mp3:
// onFail → экран дальше работает как без аватара. Под образом — только «Интервьюер: говорит / слушает» (решение владельца).
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { apiUrl, tokenStore } from "../../lib/api";
import { InterviewerAvatar } from "./InterviewerAvatar";
import { WAVE_LABEL, type WaveState } from "./VoiceWave";

const RATE = 16000;                 // pcm_s16le, моно
const CHUNK = 4096;                 // байт за сообщение (~128 мс)
const CONNECT_TIMEOUT_MS = 12000;   // не дождались видео — откат

type AnamSdk = typeof import("@anam-ai/js-sdk");
type AnamClient = ReturnType<AnamSdk["createClient"]>;
type AudioIn = ReturnType<AnamClient["createAgentAudioInputStream"]>;

interface TokenOut { session_token: string; max_seconds: number; ice_servers?: RTCIceServer[] | null; relay_only?: boolean; persona_name?: string }

export type AnamStatus = "connecting" | "live" | "failed";

export interface AnamHandle {
  /** Поток готов: можно отдавать звук реплики. */
  live(): boolean;
  /** Озвучить реплику (pcm_s16le 16 кГц моно): губы в потоке, звук — из потока. Разрешается, когда реплика договорена; сбой → reject. */
  speak(pcm: ArrayBuffer): Promise<void>;
  /** Прервать текущую реплику (ответ кандидата, «Закончить»). */
  stop(): void;
}

export interface AnamAvatarProps {
  sessionId: string;
  /** Состояние с экрана (думаю / слушаю …); «говорю» компонент выставляет сам, пока идёт звук реплики. */
  state: WaveState;
  level?: () => number;
  name?: string;
  size?: number;
  tone?: "light" | "dark";
  className?: string;
  tokenPath?: string;
  onStatus?: (s: AnamStatus) => void;
}

function rms(pcm: ArrayBuffer): Float32Array {  // огибающая громкости по 50 мс — для свечения рамки
  const s = new Int16Array(pcm, 0, Math.floor(pcm.byteLength / 2));
  const win = RATE / 20;
  const out = new Float32Array(Math.ceil(s.length / win));
  for (let i = 0; i < out.length; i++) {
    let acc = 0; const a = i * win, b = Math.min(s.length, a + win);
    for (let k = a; k < b; k++) acc += (s[k] / 32768) ** 2;
    out[i] = Math.min(1, Math.sqrt(acc / Math.max(1, b - a)) * 3);
  }
  return out;
}

export const AnamAvatar = forwardRef<AnamHandle, AnamAvatarProps>(function AnamAvatar(
  { sessionId, state, level, name = "Интервьюер", size = 200, tone = "light", className = "", tokenPath, onStatus }, ref,
) {
  const videoId = `anam-video-${sessionId.slice(0, 8)}`;
  const client = useRef<AnamClient | null>(null);
  const audioIn = useRef<AudioIn | null>(null);
  const [status, setStatus] = useState<AnamStatus>("connecting");
  const statusRef = useRef<AnamStatus>("connecting");
  const [speaking, setSpeaking] = useState(false);
  const env = useRef<{ t0: number; e: Float32Array } | null>(null);
  const timer = useRef<number | null>(null);
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;

  const set = (s: AnamStatus) => { if (statusRef.current === "failed") return; statusRef.current = s; setStatus(s); onStatusRef.current?.(s); };

  useEffect(() => {
    let dead = false;
    let watchdog = 0;
    (async () => {
      try {
        if (typeof RTCPeerConnection === "undefined") throw new Error("no webrtc");
        const t = tokenStore.get();
        const url = tokenPath ?? `/interview/sessions/${sessionId}/avatar-token`;
        const r = await fetch(apiUrl(url), { method: "POST", headers: t ? { Authorization: `Bearer ${t}` } : {} });
        if (!r.ok) throw new Error(String(r.status));
        const tok = (await r.json()) as TokenOut;
        if (dead) return;
        const sdk: AnamSdk = await import("@anam-ai/js-sdk");  // ленивый импорт: без флага код поставщика не грузится
        if (dead) return;
        const c = sdk.createClient(tok.session_token, {
          disableInputAudio: true,  // микрофон — только наша запись «нажми и говори», в поток не идёт
          ...(tok.ice_servers?.length ? { iceServers: tok.ice_servers } : {}),
          ...(tok.relay_only ? { rtcConfiguration: { iceTransportPolicy: "relay" as RTCIceTransportPolicy } } : {}),
        });
        client.current = c;
        c.addListener(sdk.AnamEvent.CONNECTION_CLOSED, () => { if (!dead) fail(); });
        c.addListener(sdk.AnamEvent.VIDEO_PLAY_STARTED, () => { if (dead) return; window.clearTimeout(watchdog); set("live"); });
        watchdog = window.setTimeout(() => { if (!dead && statusRef.current !== "live") fail(); }, CONNECT_TIMEOUT_MS);
        await c.streamToVideoElement(videoId);
        if (dead) { void c.stopStreaming().catch(() => undefined); return; }
        audioIn.current = c.createAgentAudioInputStream({ encoding: "pcm_s16le", sampleRate: RATE, channels: 1 });
        // предел сессии у поставщика — за 5 с до него тихо уходим на портрет, не дожидаясь обрыва
        window.setTimeout(() => { if (!dead) fail(); }, Math.max(30, (tok.max_seconds || 600) - 5) * 1000);
      } catch { if (!dead) fail(); }
    })();
    function fail() {
      window.clearTimeout(watchdog);
      const c = client.current; client.current = null; audioIn.current = null;
      void c?.stopStreaming().catch(() => undefined);
      if (timer.current) window.clearTimeout(timer.current);
      setSpeaking(false);
      if (statusRef.current !== "failed") { statusRef.current = "failed"; setStatus("failed"); onStatusRef.current?.("failed"); }
    }
    return () => {
      dead = true; window.clearTimeout(watchdog);
      if (timer.current) window.clearTimeout(timer.current);
      const c = client.current; client.current = null; audioIn.current = null;
      void c?.stopStreaming().catch(() => undefined);
    };
  }, [sessionId]);  // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({
    live: () => statusRef.current === "live" && !!audioIn.current,
    speak: (pcm: ArrayBuffer) => new Promise<void>((resolve, reject) => {
      const a = audioIn.current;
      if (!a || statusRef.current !== "live" || pcm.byteLength < 2) { reject(new Error("anam not live")); return; }
      try {
        if (timer.current) window.clearTimeout(timer.current);
        for (let i = 0; i < pcm.byteLength; i += CHUNK) a.sendAudioChunk(pcm.slice(i, Math.min(pcm.byteLength, i + CHUNK)));
        a.endSequence();
      } catch (e) { reject(e); return; }
      env.current = { t0: performance.now(), e: rms(pcm) };
      setSpeaking(true);
      const ms = (pcm.byteLength / 2 / RATE) * 1000 + 400;  // длительность звука + задержка потока
      timer.current = window.setTimeout(() => { setSpeaking(false); env.current = null; timer.current = null; resolve(); }, ms);
    }),
    stop: () => {
      if (timer.current) { window.clearTimeout(timer.current); timer.current = null; }
      env.current = null; setSpeaking(false);
      try { client.current?.interruptPersona(); } catch { /* поток уже закрыт */ }
    },
  }), []);

  if (status === "failed") return <InterviewerAvatar state={state} level={level} name={name} size={size} tone={tone} className={className} />;

  const shown: WaveState = speaking ? "speaking" : state === "speaking" ? "listening" : state;
  const lvl = () => {
    const e = env.current;
    if (!e) return level?.() ?? 0;
    const i = Math.floor((performance.now() - e.t0) / 50);
    return i < e.e.length ? e.e[i] : 0;
  };
  const label = WAVE_LABEL[shown].toLowerCase();
  const textTone = tone === "dark" ? "text-white" : "text-brand-night";
  return (
    <figure className={`m-0 flex flex-col items-center text-center ${className}`} data-testid="interviewer-avatar" data-state={shown}
      data-mode={status === "live" ? "anam" : "connecting"}>
      <div className="relative aspect-square max-w-full overflow-hidden rounded-3xl bg-[#1B1C21]" style={{ width: size }}>
        {status !== "live" && (  // пока поток поднимается — наш портрет; живое видео появляется поверх без мигания
          <div className="absolute inset-0"><InterviewerAvatar state={shown} level={lvl} name={name} size={size} tone={tone} className="[&>figcaption]:hidden" /></div>
        )}
        <video id={videoId} autoPlay playsInline disablePictureInPicture aria-label="ИИ-интервьюер: сгенерированный образ, не человек"
          className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${status === "live" ? "opacity-100" : "opacity-0"}`}
          data-testid="avatar-anam-video" />
        <RingGlow state={shown} level={lvl} />
      </div>
      <figcaption className="mt-2">
        <p className={`text-sm font-semibold ${textTone}`}>
          {name}: <span aria-live="polite" data-testid="avatar-state">{label}</span>
        </p>
      </figcaption>
    </figure>
  );
});

const RING: Record<WaveState, string> = {
  idle: "rgba(138,131,209,0.55)", speaking: "rgba(64,47,255,0.95)", listening: "rgba(95,87,184,0.9)", thinking: "rgba(192,21,122,0.75)",
};

/** Свечение рамки по громкости реплики — как у портрета, чтобы переход поток ↔ портрет был незаметен. */
function RingGlow({ state, level }: { state: WaveState; level: () => number }) {
  const el = useRef<HTMLDivElement | null>(null);
  const st = useRef(state); st.current = state;
  const lv = useRef(level); lv.current = level;
  useEffect(() => {
    let raf = 0, smooth = 0;
    const draw = () => {
      const s = st.current;
      const raw = s === "speaking" || s === "listening" ? Math.max(0, Math.min(1, lv.current())) : 0;
      smooth += (raw - smooth) * 0.3;
      if (el.current) el.current.style.boxShadow = `inset 0 0 0 3px ${RING[s]}, inset 0 0 ${Math.round(10 + 34 * smooth)}px ${Math.round(2 + 8 * smooth)}px ${RING[s]}`;
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <div ref={el} aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-3xl" />;
}

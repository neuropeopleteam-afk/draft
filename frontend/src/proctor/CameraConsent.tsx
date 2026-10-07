/**
 * Экран камеры перед тестом: честное описание того, что делает камера, две равноправные кнопки —
 * «Включить камеру» и «Пройти без камеры». Показывается до создания сессии теста (первое задание банк
 * выдаёт при создании сессии). Любая ошибка камеры или модели — понятное сообщение и продолжение без камеры.
 */
import { useEffect, useRef, useState } from "react";
import { Alert, Loading, errText } from "../components/ui";
import { api } from "../lib/api";
import { camera, stateTitle, useCamera } from "./controller";

export type CamMode = "camera" | "declined" | "unsupported" | "denied";

export interface ConsentText {
  title: string; what: string[]; stored: string[]; how_long: string; who_sees: string[]; effect: string; revoke: string; operator: string; version: string;
}
export interface ConsentState { active: boolean; granted_at: string | null; version: string | null; current_version: string; text: ConsentText; enabled: boolean }

/** Текст согласия — общий для экрана перед тестом и настроек. */
export function ConsentBody({ t, compact = false }: { t: ConsentText; compact?: boolean }) {
  const cls = compact ? "text-xs" : "text-sm";
  return (
    <div className={`space-y-3 leading-relaxed text-brand-ink/80 ${cls}`}>
      <Block title="Что делает камера" items={t.what} />
      <Block title="Что сохраняется" items={t.stored} />
      <Block title="Кто это видит" items={t.who_sees} />
      <p><b className="text-brand-night">Как влияет на результат.</b> {t.effect}</p>
      <p><b className="text-brand-night">Срок хранения.</b> {t.how_long}</p>
      <p><b className="text-brand-night">Отзыв согласия.</b> {t.revoke}</p>
      <p className="text-xs text-brand-ink/65">Оператор: {t.operator}. Редакция согласия: {t.version}.</p>
    </div>
  );
}

function Block({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="font-semibold text-brand-night">{title}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 marker:text-brand">{items.map((s, i) => <li key={i}>{s}</li>)}</ul>
    </div>
  );
}

/** Сообщить серверу режим камеры для созданной сессии. Ошибка не прерывает тест: камера просто выключается. */
export async function startProctor(sessionId: string, mode: CamMode, reason?: string | null): Promise<void> {
  try {
    await api(`/proctor/sessions/${sessionId}/start`, { body: { mode, reason: reason ?? null, client: mode === "camera" ? camera.clientInfo() : null } });
    if (mode === "camera") camera.attachSession(sessionId);
  } catch (e) {
    if (mode === "camera") await camera.stop("navigate");
    throw e;
  }
}

/** Живое превью с камеры (только на экране кандидата) и статус «лицо в кадре». */
export function CameraPreview({ small = false }: { small?: boolean }) {
  const cam = useCamera();
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    v.srcObject = cam.status === "on" ? camera.mediaStream : null;
    if (cam.status === "on") v.play().catch(() => undefined);
  }, [cam.status]);
  const ok = cam.state === "face";
  return (
    <div className={`flex ${small ? "items-center gap-3" : "flex-col items-start gap-3 sm:flex-row sm:items-center"}`}>
      <video ref={ref} muted playsInline autoPlay aria-label="Изображение с вашей камеры (никуда не передаётся)"
        className={`${small ? "h-16 w-[5.33rem]" : "h-36 w-48"} shrink-0 rounded-xl bg-brand-night/90 object-cover [transform:scaleX(-1)]`} />
      <div className="text-sm">
        <p className="font-semibold text-brand-night" data-testid="camera-state">
          <span className={`mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle ${ok ? "bg-emerald-500" : cam.state === "unknown" ? "bg-brand-lavender" : "bg-brand"}`} aria-hidden="true" />
          Камера: {stateTitle(cam.state)}
        </p>
        {!small && <p className="mt-1 text-xs text-brand-ink/65">Изображение видите только вы. Кадры анализируются в браузере, проанализировано кадров: {cam.frames}.</p>}
      </div>
    </div>
  );
}

export function CameraConsent({ onDone, onBack, busy, error }: {
  onDone: (mode: CamMode, reason?: string | null) => void; onBack: () => void; busy: boolean; error: string | null;
}) {
  const [c, setC] = useState<ConsentState | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const cam = useCamera();
  useEffect(() => { api<ConsentState>("/proctor/consent").then(setC).catch((e) => setLoadErr(errText(e))); }, []);

  async function enable() {
    setStarting(true);
    try {
      if (!c?.active) await api("/proctor/consent", { method: "POST" });
      await camera.start();
    } catch {
      // сообщение уже в состоянии камеры (cam.error); тест можно пройти без камеры
    } finally { setStarting(false); }
  }
  async function withoutCamera() {
    const code = cam.status === "error" ? cam.errorCode : null;
    await camera.stop("navigate");
    onDone(code === "denied" ? "denied" : code === "unsupported" ? "unsupported" : "declined", code ? cam.error : null);
  }

  if (loadErr) return <div className="max-w-2xl space-y-4"><Alert>{loadErr}</Alert><button className="btn-ghost" onClick={onBack}>Назад</button></div>;
  if (!c) return <Loading text="Загружаем условия…" />;
  const on = cam.status === "on";
  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold text-brand-night">Камера во время теста</h2>
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/75">
        По желанию: камера подтверждает работодателю, что тест вы проходили сами. Без камеры тест доступен полностью, оценка и грейд
        от неё не зависят — работодатель увидит нейтральную пометку «тест без камеры». Выбор делается перед каждым тестом заново.
      </p>
      <div className="card mt-5">
        <p className="font-bold text-brand-night">{c.text.title}</p>
        <div className="mt-3"><ConsentBody t={c.text} /></div>
      </div>
      {cam.status === "error" && cam.error && <div className="mt-4"><Alert kind="info">{cam.error}</Alert></div>}
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      {on && <div className="card mt-4"><CameraPreview /></div>}
      <div className="mt-6 flex flex-wrap gap-3">
        {on ? (
          <button className="btn-primary" disabled={busy} onClick={() => onDone("camera")}>{busy ? "Готовим задания…" : "Начать тест с камерой"}</button>
        ) : (
          <button className="btn-primary" disabled={busy || starting || cam.status === "starting" || cam.errorCode === "unsupported"} onClick={enable}>
            {starting || cam.status === "starting" ? "Включаем камеру…" : cam.status === "error" ? "Попробовать снова" : "Включить камеру"}
          </button>
        )}
        <button className="btn border-2 border-brand bg-white text-brand hover:bg-brand-blush/40" disabled={busy} onClick={withoutCamera}>{busy ? "Готовим задания…" : cam.status === "error" ? "Продолжить без камеры" : "Пройти без камеры"}</button>
        <button className="btn-ghost" disabled={busy} onClick={async () => { await camera.stop("navigate"); onBack(); }}>Назад</button>
      </div>
      <p className="mt-3 text-xs text-brand-ink/65">
        {c.active ? `Согласие на анализ видео дано ${new Date(c.granted_at!).toLocaleDateString("ru-RU")} — нажатие «Включить камеру» запрашивает доступ к камере в браузере.` : "Нажимая «Включить камеру», вы даёте согласие на анализ видео на условиях выше; отозвать его можно в настройках."}
      </p>
    </div>
  );
}

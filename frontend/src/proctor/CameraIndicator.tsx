/**
 * Индикатор камеры на странице теста: текущее состояние («лицо в кадре» и т. п.), кнопка «Выключить камеру»,
 * а после перезагрузки страницы — предложение включить камеру снова (тест при этом идёт дальше).
 */
import { useEffect, useState } from "react";
import { Alert } from "../components/ui";
import { api } from "../lib/api";
import { useMeta } from "../lib/meta";
import { CameraPreview, startProctor } from "./CameraConsent";
import { camera, stateTitle, useCamera } from "./controller";

interface View { mode: string | null; camera_active: boolean; resumes: number }

export function CameraIndicator({ sessionId }: { sessionId: string }) {
  const meta = useMeta();
  const cam = useCamera();
  const [view, setView] = useState<View | null>(null);
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [preview, setPreview] = useState(false);
  const enabled = meta?.proctor_camera !== false;
  useEffect(() => {
    if (!enabled || cam.status !== "off") return;
    api<View>(`/proctor/sessions/${sessionId}`).then(setView).catch(() => setView(null));
  }, [sessionId, enabled, cam.status]);
  if (!enabled) return null;

  async function again() {
    setBusy(true);
    try { await camera.start(); await startProctor(sessionId, "camera"); } catch { /* сообщение — в cam.error */ } finally { setBusy(false); }
  }

  if (cam.status === "on" || cam.status === "starting") {
    const ok = cam.state === "face";
    return (
      <div className="mt-3 rounded-xl border border-brand-night/10 bg-white px-3 py-2 text-xs" data-testid="camera-indicator">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold text-brand-night">
            <span className={`mr-1.5 inline-block h-2 w-2 rounded-full align-middle ${cam.status === "starting" ? "bg-brand-lavender" : ok ? "bg-emerald-500" : "bg-brand"}`} aria-hidden="true" />
            Камера: {cam.status === "starting" ? "включается" : stateTitle(cam.state)}
          </span>
          <span className="text-brand-ink/65">кадры остаются в браузере</span>
          <span className="ml-auto flex gap-3">
            <button type="button" className="font-semibold text-brand hover:underline" onClick={() => setPreview((v) => !v)}>{preview ? "Скрыть превью" : "Превью"}</button>
            <button type="button" className="font-semibold text-brand hover:underline" onClick={() => camera.stop("user")}>Выключить камеру</button>
          </span>
        </div>
        {preview && cam.status === "on" && <div className="mt-2"><CameraPreview small /></div>}
      </div>
    );
  }
  if (cam.status === "error" && cam.error && !dismissed) {
    return (
      <div className="mt-3"><Alert kind="info">{cam.error} Тест продолжается. <button type="button" className="font-semibold underline" onClick={() => setDismissed(true)}>Понятно</button></Alert></div>
    );
  }
  if (cam.status === "off" && view?.mode === "camera" && view.camera_active && !dismissed) {
    return (
      <div className="mt-3" data-testid="camera-resume">
        <Alert kind="info">
          Камера выключена — после перезагрузки страницы браузер требует включить её заново. Тест идёт дальше; время без камеры будет отмечено в итоге.
          <span className="mt-2 flex flex-wrap gap-3">
            <button type="button" className="font-semibold underline" disabled={busy} onClick={again}>{busy ? "Включаем…" : "Включить камеру снова"}</button>
            <button type="button" className="font-semibold underline" onClick={() => setDismissed(true)}>Продолжить без камеры</button>
          </span>
        </Alert>
      </div>
    );
  }
  if (cam.status === "off" && cam.error && !dismissed) {
    return <div className="mt-3"><Alert kind="info">{cam.error} <button type="button" className="font-semibold underline" onClick={() => setDismissed(true)}>Понятно</button></Alert></div>;
  }
  if (cam.status === "off" && view?.mode === "camera") {
    return (
      <p className="mt-3 text-xs text-brand-ink/65" data-testid="camera-off">
        Камера выключена, тест идёт без неё. <button type="button" className="font-semibold text-brand hover:underline" disabled={busy} onClick={again}>{busy ? "Включаем…" : "Включить снова"}</button>
      </p>
    );
  }
  return null;
}

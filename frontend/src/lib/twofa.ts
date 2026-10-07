// Второй фактор входа (TOTP): передача «вызова» между шагом пароля и экраном ввода кода (/login/2fa).
// Промежуточный токен живёт 5 минут и в кабинет не пускает (сервер отвергает его везде, кроме /api/auth/2fa/*),
// поэтому хранится в sessionStorage — только на время шага и только в этой вкладке.
import type { TwoFactorChallenge } from "./api";

const KEY = "fsp_twofa_challenge";

export interface StoredChallenge extends TwoFactorChallenge { next: string; started_at: number }

export const pending = {
  get: (): StoredChallenge | null => {
    try {
      const raw = sessionStorage.getItem(KEY);
      if (!raw) return null;
      const c = JSON.parse(raw) as StoredChallenge;
      if (Date.now() - c.started_at > c.expires_in * 1000) { sessionStorage.removeItem(KEY); return null; }
      return c;
    } catch { return null; }
  },
  set: (c: TwoFactorChallenge, next: string) => sessionStorage.setItem(KEY, JSON.stringify({ ...c, next, started_at: Date.now() } satisfies StoredChallenge)),
  clear: () => sessionStorage.removeItem(KEY),
};

/** Сохранить вызов и вернуть адрес экрана кода. next — куда вести после входа (по умолчанию landing с сервера). */
export function challengePath(c: TwoFactorChallenge, next?: string | null): string {
  pending.set(c, next || c.landing || "/");
  return "/login/2fa";
}

/** Разбить 6 цифр как в приложении: «123 456». */
export const groupDigits = (s: string) => s.replace(/\D/g, "").slice(0, 6).replace(/(\d{3})(\d)/, "$1 $2");

/** Файл с резервными кодами — чтобы сохранить их не только на экране. */
export function downloadCodes(codes: string[], account: string, product: string) {
  const text = [`${product} — резервные коды второго фактора`, `Учётная запись: ${account}`, `Выпущены: ${new Date().toLocaleString("ru-RU")}`,
    "Каждый код действует один раз. Храните отдельно от пароля.", "", ...codes, ""].join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = "rezervnye-kody.txt"; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

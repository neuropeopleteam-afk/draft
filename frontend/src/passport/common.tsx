// Паспорт грейда: общие типы и подписи статусов (публичная страница, кабинет кандидата, карточка работодателя).
import type { ReactNode } from "react";

export type PassportState = "valid" | "revoked" | "expired" | "invalid_signature";

export interface PassportClaims {
  schema: string; id: string; kid: string; issued_at: string; valid_until: string; methodology_url: string;
  issuer: { name: string; url: string; jwks_url: string; test_key?: boolean };
  subject: { public_ref: string };
  category: { id: string; title: string; direction: string; direction_title: string; grade: string; grade_title: string };
  grade_status: "confirmed" | "preliminary";
  assessment: null | {
    test_date: string | null; engine: string | null; theta: number | null; se: number | null;
    p_grade_or_higher: number | null; answered: number | null; correct: number | null; integrity: string | null;
  };
  skills_t1: { tag: string; title: string; score: number | null }[];
  achievements_t2: {
    discipline: string; discipline_title: string; event: string; level: string; level_title: string; date: string | null;
    place: number | null; result: string | null; source: { registry: string; ref: string | null; demo: boolean };
  }[];
}

export interface PassportStatus {
  state: PassportState; title: string; reason: string | null; reason_title: string | null; revoked_at: string | null;
  issued_at: string; valid_until: string; checked_at: string; signature_valid: boolean; kid_known: boolean; test_key: boolean;
}

export interface PassportPublic {
  passport: PassportClaims; document: string; signature: { alg: string; kid: string; value: string };
  status: PassportStatus; keys: Record<string, unknown>[]; verify_url: string; canonicalization: string;
}

export const STATE_STYLE: Record<PassportState, string> = {
  valid: "border-emerald-200 bg-emerald-50 text-emerald-900",
  revoked: "border-brand/30 bg-brand-blush/40 text-brand-plum",
  expired: "border-amber-200 bg-amber-50 text-amber-900",
  invalid_signature: "border-brand/40 bg-brand-blush/60 text-brand-plum",
};

export const STATE_HINT: Record<PassportState, string> = {
  valid: "Подпись платформы верна, паспорт не отозван и срок не истёк.",
  revoked: "Паспорт отозван — опираться на него нельзя.",
  expired: "Срок действия паспорта истёк — грейд нужно подтвердить заново.",
  invalid_signature: "Содержимое не совпадает с подписью платформы: паспорт изменён или подделан.",
};

export const GRADE_STATUS: Record<string, string> = { confirmed: "грейд подтверждён", preliminary: "грейд предварительный" };
export const INTEGRITY: Record<string, string> = { high: "высокая", medium: "средняя", low: "низкая" };

export function StateBadge({ state, children }: { state: PassportState; children?: ReactNode }) {
  const dot: Record<PassportState, string> = { valid: "bg-emerald-600", revoked: "bg-brand", expired: "bg-amber-500", invalid_signature: "bg-brand" };
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${STATE_STYLE[state]}`}>
      <span className={`h-2 w-2 rounded-full ${dot[state]}`} aria-hidden="true" />{children}
    </span>
  );
}

/** Ссылка на публичную проверку — от адреса текущей страницы (стенд, локальный стек). */
export const verifyHref = (id: string) => `${window.location.origin}/verify/${id}`;

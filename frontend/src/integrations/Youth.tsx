import { useState } from "react";
import { Alert, Field, Toggle, errText } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

export function YouthProfile({ onSaved }: { onSaved: () => void }) {
  const { me, refresh } = useAuth();
  const [age, setAge] = useState(me?.candidate?.age_group ?? "18+");
  const [consent, setConsent] = useState(me?.candidate?.parental_consent ?? false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{kind: "ok" | "error"; text: string} | null>(null);
  async function save() {
    setBusy(true); setMessage(null);
    try {
      await api("/me/candidate-profile", { method: "PATCH", body: { age_group: age, parental_consent: age !== "18+" && consent } });
      await refresh(); onSaved(); setMessage({ kind: "ok", text: "Условия сохранены. Возраст не участвует в рейтинге и подборе." });
    } catch (e) { setMessage({kind: "error", text: errText(e)}); }
    finally { setBusy(false); }
  }
  return <section className="card space-y-4" data-testid="youth-profile">
    <h2 className="font-bold text-brand-night">Возрастная группа и условия работы</h2>
    <p className="text-sm text-brand-ink/70">Не спрашиваем дату рождения. Возраст не влияет на место в выдаче: он нужен только для безопасных условий приглашения.</p>
    <Field label="Возрастная группа" htmlFor="age-group">
      <select id="age-group" data-testid="select-age-group" className="input" value={age} onChange={e => {setAge(e.target.value); setConsent(false);}}>
        <option value="18+">18 лет и старше</option><option value="16-17">16–17 лет</option><option value="14-15">14–15 лет</option>
      </select>
    </Field>
    {age !== "18+" && <>
      <Toggle checked={consent} onChange={setConsent} label="Получено согласие родителя или законного представителя на обработку данных" hint="Это ваша отметка, не проверка документов. Подтверждающие документы проверяются перед оформлением." />
      <Alert kind="info">{age === "16-17" ? "Можно получить предложение стажировки или лёгкого труда с сокращённым временем. Работодатель увидит ограничения, но не дату рождения." : "Профиль и тест доступны. Офферы для 14–15 лет пока не поддерживаются: условия требуют отдельной проверки."}</Alert>
    </>}
    {message && <Alert kind={message.kind}>{message.text}</Alert>}
    <button className="btn-primary" data-testid="button-youth-save" disabled={busy} onClick={save}>{busy ? "Сохраняем…" : "Сохранить условия"}</button>
  </section>;
}

export function EmploymentTermsText({ terms }: { terms?: any }) {
  if (!terms || (terms.format === "employment" && !terms.reduced_time)) return null;
  const title = terms.format === "internship" ? "Стажировка" : terms.format === "light_work" ? "Лёгкий труд" : "Работа";
  return <p className="rounded-xl bg-[#F3F2FB] p-3 text-sm text-brand-night">{title}{terms.reduced_time ? " · сокращённое рабочее время" : ""}. Условия оформления проверяет работодатель.</p>;
}

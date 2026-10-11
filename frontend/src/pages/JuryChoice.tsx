import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { Alert, errText, NB } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useQuickSteps } from "../components/JuryQuick";
import { guide, quick, QUICK_MINUTES, startQuick, STEPS } from "../lib/jury";
import { usePageTitle } from "../lib/meta";

/** Я9: /jury/go без роли и экрана — выбор режима проводника жюри. «Проверка за 12 минут» (QUICK) или полный
 *  справочник (STEPS). /jury/go?tour=12 и ?tour=full — сразу нужный режим (ссылка для материалов сдачи). */
export default function JuryChoice({ tour }: { tour: string | null }) {
  usePageTitle("Проверка для жюри: 12 минут или справочник");
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const steps = useQuickSteps();  // с устной защитой (флаг Я15) — 8 + 1 по желанию

  async function startQ() {
    setBusy(true); setErr(null);
    try { navigate(await startQuick(signIn), { replace: !!tour }); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  function startFull() {
    quick.setMode("full"); guide.enable(); guide.show(); guide.setStep(0);
    navigate("/register?role=candidate", { replace: !!tour });
  }
  useEffect(() => { if (tour === "12") void startQ(); else if (tour === "full") startFull(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content px-4 py-10 sm:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-plum">Для экспертов жюри</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-brand-night md:text-4xl">Как будете проверять?</h1>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-brand-ink/75">
          У каждого эксперта своя копия демо: ваши действия и сброс не видны другим. Режим можно сменить в любой момент в шапке проводника.
        </p>
        {err && <div className="mt-4"><Alert>{err}</Alert></div>}
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <section className="card flex flex-col p-5 sm:p-6" aria-labelledby="quick-t" data-testid="choice-quick">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{steps.length} шагов · около {QUICK_MINUTES} минут</p>
            <h2 id="quick-t" className="mt-1 text-xl font-extrabold text-brand-night">Проверка за 12 минут</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-brand-ink/75">Главный сценарий ТЗ своими руками: вы пишете свою потребность, приглашаете кандидата из подборки и отвечаете за него, проходите экспресс-тест и открываете доказательства.</p>
            <ol className="mt-4 space-y-2 text-sm">
              {steps.map((s, i) => (
                <li key={s.title} className="flex gap-3">
                  <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${s.optional ? "border border-dashed border-brand-night text-brand-night" : "bg-brand-night text-white"}`}>{i + 1}</span>
                  <span className="min-w-0">
                    <b className="text-brand-night">{s.title}</b> <span className="tabular-nums text-brand-ink/65">≈{NB}{String(s.min).replace(".", ",")}{NB}мин{s.optional ? " сверх плана" : ""}</span>
                    <span className="block text-xs leading-snug text-brand-ink/70">Проверяет {s.checks}. Критерий {s.crit}.</span>
                  </span>
                </li>
              ))}
            </ol>
            <div className="mt-auto pt-5">
              <button type="button" className="btn-primary" disabled={busy} onClick={startQ}>{busy ? "Входим…" : "Начать: войти как работодатель"}</button>
            </div>
          </section>
          <section className="card flex flex-col p-5 sm:p-6" aria-labelledby="full-t" data-testid="choice-full">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{STEPS.length} шагов · справочник</p>
            <h2 id="full-t" className="mt-1 text-xl font-extrabold text-brand-night">Полный справочник</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-brand-ink/75">Все функции по порядку с подробными объяснениями: регистрация, полный тест, паспорт грейда, статусы грейда, «Что если», подписки, кубки, переписка, передача в ATS, кабинет ФСП, второй фактор, живая демонстрация по QR.</p>
            <p className="mt-2 text-xs leading-relaxed text-brand-ink/65">Полный тест на грейд — 8–16 заданий и дотестирование у порога, планируйте до 80 минут; в проверке за 12 минут вместо него — экспресс-тест краткого режима жюри.</p>
            <div className="mt-auto flex flex-wrap gap-2 pt-5">
              <button type="button" className="btn-ghost" disabled={busy} onClick={startFull}>Начать справочник с регистрации</button>
              <Link to="/#jury" className="btn-ghost" onClick={() => quick.setMode("full")}>Выбрать роль на главной</Link>
            </div>
          </section>
        </div>
        <p className="mt-6 text-sm text-brand-ink/75">
          Свериться с разделом 6 ТЗ по подпунктам — <Link to="/criteria" className="font-semibold text-brand-plum underline-offset-2 hover:underline">проверка по критериям ТЗ</Link>; метрики и атаки — <Link to="/validation" className="font-semibold text-brand-plum underline-offset-2 hover:underline">как мы проверяем себя</Link>.
        </p>
      </main>
      <SiteFooter />
    </div>
  );
}

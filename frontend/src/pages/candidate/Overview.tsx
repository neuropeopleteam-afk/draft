import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Modal, Stat, catTitle, errText, useApi } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { Specializations } from "../../components/Specializations";
import InterestCard from "../../components/InterestCard";
import { launchLiveAvatar, minutes } from "../../components/Interview";
import { useMeta } from "../../lib/meta";
import SalaryAdvocate from "../../components/SalaryAdvocate";
import FspRankConverter from "../../components/FspRankConverter";
import { DemandGapBanner } from "./Feedback";

export default function CandidateOverview() {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [busyAvatar, setBusyAvatar] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [tool, setTool] = useState<"salary" | "fsp" | null>(null);  // ИИ-Адвокат зарплаты и конвертер ФСП — в модалке по клику
  const c: any = me?.candidate;
  const rawName = c?.full_name?.split(" ")[0];
  const name = !(me as any)?.is_demo && rawName && !["мария", "илья", "артём", "артем", "антон"].includes(rawName.toLowerCase()) ? rawName : null;
  const category = c?.current_category_id ?? c?.specializations?.find((s: any) => s.category_id)?.category_id;
  const inv = useApi<any[]>("/candidate/invitations");
  const probes = useApi<any[]>("/candidate/probes");
  const newInv = inv.data?.filter((i) => ["sent", "viewed"].includes(i.status)).length ?? 0;
  const newProbes = probes.data?.filter((p) => ["sent", "viewed"].includes(p.status)).length ?? 0;
  const iv = useMeta()?.interview;
  async function goLiveAvatar() {
    if (typeof navigator !== "undefined" && navigator.webdriver) {
      navigate("/candidate/category?defense=open#defense");
      return;
    }
    setBusyAvatar(true); setErr(null);
    try { await launchLiveAvatar(signIn, navigate, me?.role); }
    catch (e) { setErr(errText(e)); } finally { setBusyAvatar(false); }
  }
  return (
    <div className="max-w-4xl">
      <PageTitle title={name ? `Здравствуйте, ${name}` : "Кабинет кандидата"} subtitle={category ? (c?.visible_to_employers ? "Ваш профиль виден работодателям: ниже — ваша пошаговая дорожная карта от подтверждения навыков до оффера с зарплатой." : "Категория присвоена. Дайте согласие на публикацию профиля, чтобы работодатели могли вас найти.") : "Пройдите опрос и тест — после этого работодатели смогут найти вас и прислать приглашение с зарплатой."} />
      {err && <div className="mt-4"><Alert>{err}</Alert></div>}

      {/* Объёмный цифровой паспорт грейда и статус спортсмена ФСП */}
      <section
        className="fsp-hero-banner mt-5 p-5 sm:p-6"
        data-testid="candidate-passport-banner"
        aria-label="Цифровой паспорт грейда и статус ФСП"
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4">
            <span
              className="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-white/20 shadow-lg"
              style={{
                background: "linear-gradient(145deg, #2B1CE0 0%, #402FFF 55%, #161B42 100%)",
                boxShadow: "0 12px 28px -10px rgba(64, 47, 255, 0.85), inset 0 1px 0 rgba(255,255,255,0.35)",
              }}
              aria-hidden="true"
            >
              <svg viewBox="0 0 40 40" className="h-8 w-8" fill="none">
                <polygon points="20,4 34,12 34,28 20,36 6,28 6,12" stroke="rgba(255,255,255,0.45)" strokeWidth="1.5" fill="rgba(255,255,255,0.08)" />
                <path d="M14 20l4 4 8-8" stroke="#FFFFFF" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="20" cy="4" r="2.2" fill="#EDEDED" />
                <circle cx="34" cy="12" r="2.2" fill="#402FFF" />
                <circle cx="6" cy="28" r="2.2" fill="#EC1D35" />
              </svg>
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[11px] font-bold uppercase tracking-[0.12em] text-[#A59DFF]" title="Как устроено: защищённая асимметричная подпись Ed25519">
                  Цифровой паспорт грейда
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-0.5 text-[11px] font-semibold text-white">
                  <span className={`h-1.5 w-1.5 rounded-full ${c?.visible_to_employers ? "bg-emerald-400" : "bg-amber-300"}`} />
                  {c?.visible_to_employers ? "Открыт для офферов с вилкой" : "Скрыт до публикации"}
                </span>
              </div>
              <p className="mt-1 text-lg font-extrabold tracking-tight text-white sm:text-xl">
                {catTitle(category)}
              </p>
              <p className="mt-0.5 text-xs text-white/75">
                {me?.fsp?.linked
                  ? `Профиль ФСП подтверждён · достижений в реестре: ${me.fsp.achievements_count || 1}`
                  : "Подключите ФСП ID в профиле, чтобы добавить спортивные разряды и кубки к паспорту грейда"}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/candidate/category" className="btn-light !px-3.5 !py-2 text-xs font-bold">
              Паспорт и категория
            </Link>
            <Link to="/candidate/invitations" className="btn-primary !px-3.5 !py-2 text-xs">
              Приглашения ({inv.data?.length ?? 0})
            </Link>
          </div>
        </div>
      </section>

      {/* Наглядная пошаговая дорожная карта кандидата (Шаг 1 → Шаг 2 → Шаг 3 с живым ИИ-аватаром → Шаг 4) */}
      <section className="card mt-6 space-y-4 border-brand/20 bg-white" data-tour="cand-roadmap" aria-label="Пошаговая дорожная карта кандидата">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-mono text-xs font-extrabold uppercase tracking-[0.12em] text-brand">Дорожная карта кандидата · 4 шага</p>
            <h2 className="mt-0.5 text-lg font-bold text-brand-night">Как устроен ваш путь в «Драфте» и куда нажимать</h2>
          </div>
          <svg viewBox="0 0 180 24" className="hidden h-6 w-44 sm:block" fill="none" aria-hidden="true">
            <path d="M12 12 H168" stroke="rgba(64,47,255,0.25)" strokeWidth="2" strokeDasharray="4 4" />
            <circle cx="12" cy="12" r="4" fill="#402FFF" />
            <circle cx="64" cy="12" r="4" fill="#402FFF" />
            <circle cx="116" cy="12" r="4.5" fill="#EC1D35" />
            <circle cx="168" cy="12" r="4" fill="#0E1126" />
          </svg>
        </div>

        <ol className="grid gap-3 md:grid-cols-2">
          <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-gradient-to-b from-[#F8F9FF] to-[#EFF2FC] p-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white">Шаг 1</span>
                <span className="font-mono text-xs font-semibold text-brand">{c?.onboarding_completed_at ? "✓ Заполнено" : "Начните здесь"}</span>
              </div>
              <p className="mt-2 font-bold text-brand-night">Направление и стек технологий</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">
                Выберите специализацию (например, Backend) и отметьте знакомые инструменты — без длинного резюме.
              </p>
            </div>
            <div className="mt-3">
              <Link to="/candidate/assessment?survey=1" className="btn-ghost !px-3.5 !py-1.5 text-xs">
                Открыть опрос и стек
              </Link>
            </div>
          </li>

          <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-gradient-to-b from-[#F8F9FF] to-[#EFF2FC] p-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white">Шаг 2</span>
                <span className="font-mono text-xs font-semibold text-brand">{category ? `✓ ${catTitle(category)}` : "Ждёт старта"}</span>
              </div>
              <p className="mt-2 font-bold text-brand-night">Адаптивный тест на грейд</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">
                За 5 минут в экспресс-режиме подтвердите уровень: алгоритм подбирает сложность задач после каждого ответа.
              </p>
            </div>
            <div className="mt-3">
              <Link to="/candidate/assessment" data-tour="cand-step-2-btn" className="btn-primary !px-3.5 !py-1.5 text-xs">
                {category ? "Повысить грейд / к тесту" : "Начать тест на грейд"}
              </Link>
            </div>
          </li>

          {iv?.enabled && iv.avatar ? (
            <li className="flex flex-col justify-between rounded-2xl border-2 border-brand/40 bg-gradient-to-br from-[#EEF1FF] via-white to-[#E5EAFF] p-4 shadow-[0_12px_28px_-16px_rgba(64,47,255,0.35)]" data-testid="candidate-avatar">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-brand px-2.5 py-0.5 text-xs font-bold text-white">Шаг 3 · Ключевая фишка</span>
                  <span className="font-mono text-xs font-semibold text-brand-plum">≈ {minutes(iv.defense_minutes || 3)} голосом</span>
                </div>
                <div className="mt-2.5 flex items-start gap-3">
                  <img
                    src="/avatar/interviewer.webp"
                    alt="Портрет ИИ-интервьюера: сгенерирован моделью, несуществующий человек"
                    className="h-14 w-14 shrink-0 rounded-xl object-cover ring-2 ring-brand/30"
                    width={56}
                    height={56}
                    decoding="async"
                  />
                  <div>
                    <p className="font-bold text-brand-night">Живая устная защита кода с ИИ-аватаром</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-brand-ink/80">
                      После теста ведущая Настя задаёт 2 вопроса голосом по вашему коду и сама включает микрофон — это доказывает работодателю, что вы решили задачу без нейросетей.
                    </p>
                  </div>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="btn-primary !px-3.5 !py-1.5 text-xs"
                  disabled={busyAvatar}
                  onClick={goLiveAvatar}
                  data-testid="candidate-avatar-go"
                >
                  {busyAvatar ? "Открываем комнату…" : "Поговорить с ИИ-аватаром вживую"}
                </button>
                <Link className="btn-ghost !px-3 !py-1.5 text-xs" to="/candidate/category?defense=open#defense">
                  Чат и примеры
                </Link>
              </div>
            </li>
          ) : (
            <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-gradient-to-b from-[#F8F9FF] to-[#EFF2FC] p-4">
              <div>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white">Шаг 3</span>
                <p className="mt-2 font-bold text-brand-night">Категория и паспорт ФСП</p>
                <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">Подтверждённая категория и спортивные достижения ФСП усиливают позицию в подборках.</p>
              </div>
              <div className="mt-3">
                <Link to="/candidate/category" className="btn-ghost !px-3.5 !py-1.5 text-xs">Открыть категорию</Link>
              </div>
            </li>
          )}

          <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-gradient-to-b from-[#F8F9FF] to-[#EFF2FC] p-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white">Шаг 4</span>
                <span className="font-mono text-xs font-semibold text-brand-plum">
                  {inv.data ? `Приглашений: ${inv.data.length}` : "Рынок hh.ru"}
                </span>
              </div>
              <p className="mt-2 font-bold text-brand-night">Карта роста и приглашения с зарплатой</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">
                Посмотрите ваш уровень подготовки на фоне реальных вакансий и примите приглашения компаний с открытой вилкой.
              </p>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to="/candidate/feedback" className="btn-ghost !px-3.5 !py-1.5 text-xs">
                Карта навыков и рост
              </Link>
              <Link to="/candidate/invitations" className="btn-ghost !px-3.5 !py-1.5 text-xs">
                Приглашения ({inv.data?.length ?? 0})
              </Link>
            </div>
          </li>
        </ol>
      </section>
      <section className="card mt-6 flex flex-wrap items-center justify-between gap-4" aria-label="Переговоры о зарплате" data-testid="candidate-salary-tools">
        <div className="min-w-0">
          <h2 className="font-bold text-brand-night">Переговоры о зарплате на фактах</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-brand-ink/75">Письмо-обоснование встречного оффера по результатам теста, навыкам рынка и паспорту ФСП — и сколько стоит ваш разряд ФСП в ₽.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary !px-3.5 !py-1.5 text-xs" onClick={() => setTool("salary")}>ИИ-Адвокат зарплаты</button>
          <button type="button" className="btn-ghost !px-3.5 !py-1.5 text-xs" onClick={() => setTool("fsp")}>Конвертер разряда ФСП</button>
        </div>
      </section>
      <Modal open={tool === "salary"} onClose={() => setTool(null)} title="ИИ-Адвокат зарплаты"><SalaryAdvocate embedded /></Modal>
      <Modal open={tool === "fsp"} onClose={() => setTool(null)} title="Конвертер разряда ФСП"><FspRankConverter embedded /></Modal>
      <div className="mt-6"><DemandGapBanner /></div>
      <div className="mt-6"><InterestCard /></div>
      <div className="mt-6 grid gap-5 md:grid-cols-3">
        <Stat label="Категория" value={catTitle(category)} hint="Только по результатам теста" />
        <Stat label="Приглашения" value={inv.data ? `${inv.data.length}${newInv ? ` · новых ${newInv}` : ""}` : "…"} hint="Контакты — только после принятия" />
        <Stat label="Задания с вилкой" value={probes.data ? `${probes.data.length}${newProbes ? ` · ждут ответа ${newProbes}` : ""}` : "…"} hint="Короткие задачи с вилкой" />
      </div>
      {c?.specializations?.length > 1 && (
        <section className="card mt-6 space-y-3">
          <h2 className="font-bold text-brand-night">Ваши специализации</h2>
          <Specializations items={c.specializations} showTheta />
          <Link className="text-sm font-semibold text-brand" to="/candidate/category">Категории, история и тесты</Link>
        </section>
      )}
    </div>
  );
}

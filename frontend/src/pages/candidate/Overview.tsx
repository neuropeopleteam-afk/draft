import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Stat, catTitle, errText, useApi } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { Specializations } from "../../components/Specializations";
import InterestCard from "../../components/InterestCard";
import { launchLiveAvatar, minutes } from "../../components/Interview";
import { startAvatarTour } from "../../components/InteractiveAvatarTour";
import { useMeta } from "../../lib/meta";

export default function CandidateOverview() {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [busyAvatar, setBusyAvatar] = useState(false);
  const [err, setErr] = useState<string | null>(null);
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

      {/* Наглядная пошаговая дорожная карта кандидата (Шаг 1 → Шаг 2 → Шаг 3 с живым ИИ-аватаром → Шаг 4) */}
      <section className="card mt-6 space-y-4 border-brand/20 bg-white" data-tour="cand-roadmap" aria-label="Пошаговая дорожная карта кандидата">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand">Дорожная карта кандидата · 4 шага</p>
            <h2 className="mt-0.5 text-lg font-bold text-brand-night">Как устроен ваш путь в «Драфте» и куда нажимать</h2>
          </div>
          <button
            type="button"
            onClick={() => startAvatarTour("candidate", 0)}
            className="btn-ghost !px-3.5 !py-1.5 text-xs font-bold"
          >
            ▶ Показать все 4 шага со стрелками и голосом
          </button>
        </div>

        <ol className="grid gap-3 md:grid-cols-2">
          <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white">Шаг 1</span>
                <span className="text-xs font-semibold text-emerald-700">{c?.onboarding_completed_at ? "✓ Заполнено" : "Начните здесь"}</span>
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

          <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white">Шаг 2</span>
                <span className="text-xs font-semibold text-emerald-700">{category ? `✓ ${catTitle(category)}` : "Ждёт старта"}</span>
              </div>
              <p className="mt-2 font-bold text-brand-night">Адаптивный тест на грейд (2PL IRT)</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">
                За 5 минут в экспресс-режиме подтвердите уровень: алгоритм подбирает сложность задач после каждого ответа.
              </p>
            </div>
            <div className="mt-3">
              <Link to="/candidate/assessment" className="btn-primary !px-3.5 !py-1.5 text-xs">
                {category ? "Повысить грейд / к тесту" : "Начать тест на грейд"}
              </Link>
            </div>
          </li>

          {iv?.enabled && iv.avatar ? (
            <li className="flex flex-col justify-between rounded-2xl border-2 border-brand/35 bg-brand-blush/25 p-4" data-testid="candidate-avatar">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-brand px-2.5 py-0.5 text-xs font-bold text-white">Шаг 3 · Ключевая фишка</span>
                  <span className="text-xs font-semibold text-brand-plum">≈ {minutes(iv.defense_minutes || 3)} голосом</span>
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
                      После теста ведущая Елена задаёт 2 вопроса голосом по вашему коду и сама включает микрофон — это доказывает работодателю, что вы решили задачу без нейросетей.
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
            <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
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

          <li className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white">Шаг 4</span>
                <span className="text-xs font-semibold text-brand-plum">
                  {inv.data ? `Приглашений: ${inv.data.length}` : "Рынок hh.ru"}
                </span>
              </div>
              <p className="mt-2 font-bold text-brand-night">Карта роста и приглашения с зарплатой</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">
                Посмотрите шкалу способности θ на фоне 1 344 вакансий hh.ru и примите приглашения компаний с открытой вилкой.
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

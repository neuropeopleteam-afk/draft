import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Stat, catTitle, useApi } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { Specializations } from "../../components/Specializations";

export default function CandidateOverview() {
  const { me } = useAuth();
  const c: any = me?.candidate;
  const name = c?.full_name?.split(" ")[0];
  const category = c?.current_category_id ?? c?.specializations?.find((s: any) => s.category_id)?.category_id;
  const inv = useApi<any[]>("/candidate/invitations");
  const probes = useApi<any[]>("/candidate/probes");
  const newInv = inv.data?.filter((i) => ["sent", "viewed"].includes(i.status)).length ?? 0;
  const newProbes = probes.data?.filter((p) => ["sent", "viewed"].includes(p.status)).length ?? 0;
  const steps = [
    { done: !!me?.is_email_verified, title: "Почта подтверждена", text: "Регистрация завершена." },
    { done: !!c?.onboarding_completed_at, title: "Опрос", text: "Направление, стек и опыт — около 3 минут.", to: "assessment" },
    { done: !!category, title: "Тест на грейд", text: "Общий блок и задачи вашего направления.", to: "assessment" },
    { done: !!c?.visible_to_employers && !!category, title: "Профиль виден работодателям", text: "Нужны категория и согласие на публикацию обезличенного профиля.", to: "settings" },
  ];
  return (
    <div className="max-w-4xl">
      <PageTitle title={name ? `Здравствуйте, ${name}` : "Кабинет кандидата"} subtitle={category ? (c?.visible_to_employers ? "Ваш профиль виден работодателям: ждите приглашений с зарплатой и коротких задач." : "Категория присвоена. Дайте согласие на публикацию профиля, чтобы работодатели могли вас найти.") : "Пройдите опрос и тест — после этого работодатели смогут найти вас и прислать приглашение с зарплатой."} />
      <div className="mt-8 grid gap-5 md:grid-cols-3">
        <Stat label="Категория" value={catTitle(category)} hint="Только по результатам теста" />
        <Stat label="Приглашения" value={inv.data ? `${inv.data.length}${newInv ? ` · новых ${newInv}` : ""}` : "…"} hint="Контакты — только после принятия" />
        <Stat label="Зонды работодателей" value={probes.data ? `${probes.data.length}${newProbes ? ` · ждут ответа ${newProbes}` : ""}` : "…"} hint="Короткие задачи с вилкой" />
      </div>
      {c?.specializations?.length > 1 && (
        <section className="card mt-6 space-y-3">
          <h2 className="font-bold text-brand-night">Ваши специализации</h2>
          <Specializations items={c.specializations} />
          <Link className="text-sm font-semibold text-brand" to="/candidate/category">Категории, история и тесты</Link>
        </section>
      )}
      <section className="card mt-8">
        <h2 className="text-lg font-bold text-brand-night">Путь к первому приглашению</h2>
        <ol className="mt-5 space-y-4">
          {steps.map((s, i) => (
            <li key={s.title} className="flex items-start gap-4">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${s.done ? "bg-brand-strong text-white" : "bg-brand-blush text-brand-plum"}`}>{s.done ? "✓" : i + 1}</span>
              <div className="flex-1">
                <p className="font-semibold">{s.title}</p>
                <p className="text-sm text-brand-ink/65">{s.text}</p>
              </div>
              {!s.done && s.to && <Link to={s.to} className="text-sm font-semibold text-brand hover:text-brand-soft">Перейти</Link>}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

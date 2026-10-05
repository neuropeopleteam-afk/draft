import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { useAuth } from "../../lib/auth";

export default function CandidateOverview() {
  const { me } = useAuth();
  const c = me?.candidate;
  const name = c?.full_name?.split(" ")[0];
  const steps = [
    { done: !!me?.is_email_verified, title: "Почта подтверждена", text: "Регистрация завершена." },
    { done: false, title: "Опрос", text: "Направление, стек и опыт — около 3 минут.", to: "assessment" },
    { done: false, title: "Тест на грейд", text: "Задачи вашего направления и общий блок: алгоритмы, SQL, HTTP, Git, Linux.", to: "assessment" },
    { done: !!c?.current_category_id, title: "Категория и рейтинг", text: "После теста вы попадёте в категорию, которую видят работодатели.", to: "category" },
  ];
  return (
    <div className="max-w-4xl">
      <PageTitle title={name ? `Здравствуйте, ${name}!` : "Кабинет кандидата"} subtitle="Пройдите опрос и тест — после этого работодатели смогут найти вас и прислать приглашение с зарплатой." />
      <div className="mt-8 grid gap-5 md:grid-cols-3">
        <Stat label="Категория" value={c?.current_category_id ?? "Не присвоена"} hint="Только по результатам теста" />
        <Stat label="Приглашения" value="0" hint="Входящие предложения" />
        <Stat label="Паспорт ФСП" value={me?.fsp?.linked ? `${me.fsp.achievements_count} достиж.` : "Не связан"} hint="Без истории ФСП — без штрафа" />
      </div>
      <section className="card mt-8">
        <h2 className="text-lg font-bold text-brand-night">Путь к первому приглашению</h2>
        <ol className="mt-5 space-y-4">
          {steps.map((s, i) => (
            <li key={s.title} className="flex items-start gap-4">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${s.done ? "bg-brand text-white" : "bg-brand-blush text-brand-plum"}`}>{s.done ? "✓" : i + 1}</span>
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

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="card">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-xl font-bold text-brand-night">{value}</p>
      <p className="mt-1 text-xs text-brand-ink/55">{hint}</p>
    </div>
  );
}

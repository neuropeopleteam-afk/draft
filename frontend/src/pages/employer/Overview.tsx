import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { useAuth } from "../../lib/auth";

export default function EmployerOverview() {
  const { me } = useAuth();
  const company = me?.employer?.company;
  const steps = [
    { title: "Заполните профиль компании", text: "Кандидат увидит его в приглашении.", to: "company" },
    { title: "Опишите потребность", text: "Текстом, как в обычной вакансии, — требования структурируем автоматически.", to: "needs" },
    { title: "Посмотрите подборку", text: "Категории и обезличенные кандидаты с объяснением «почему».", to: "selections" },
    { title: "Отправьте приглашение", text: "С вилкой зарплаты «от–до» в рублях. Контакты откроются после согласия кандидата.", to: "invitations" },
  ];
  return (
    <div className="max-w-4xl">
      <PageTitle title={company?.name ?? "Кабинет работодателя"} subtitle="Найдите проверенных кандидатов по категории и выйдите на контакт первым." />
      <div className="mt-8 grid gap-5 md:grid-cols-3">
        <Stat label="Потребности" value="0" />
        <Stat label="Отправлено приглашений" value="0" />
        <Stat label="Принято" value="0" />
      </div>
      <section className="card mt-8">
        <h2 className="text-lg font-bold text-brand-night">С чего начать</h2>
        <ol className="mt-5 space-y-4">
          {steps.map((s, i) => (
            <li key={s.title} className="flex items-start gap-4">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-plum text-sm font-bold text-white">{i + 1}</span>
              <div className="flex-1">
                <p className="font-semibold">{s.title}</p>
                <p className="text-sm text-brand-ink/65">{s.text}</p>
              </div>
              <Link to={s.to} className="text-sm font-semibold text-brand hover:text-brand-soft">Перейти</Link>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-2xl font-bold text-brand-night">{value}</p>
    </div>
  );
}

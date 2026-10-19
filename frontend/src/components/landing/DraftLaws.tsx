import { useRef, useState, type KeyboardEvent } from "react";

/** W2: «Почему резюме больше не работает: 4 закона Драфта» — один набор правил продукта глазами трёх сторон.
 *  Тексты — правила, которые уже работают в продукте (вилка обязательна, контакты после согласия, обезличенный
 *  профиль, ст. 64 ТК РФ, агрегаты для ФСП), без чисел, которых нет в расчётах. */
type Who = "employer" | "candidate" | "fsp";
const WHO: [Who, string][] = [["employer", "От лица работодателя"], ["candidate", "От лица кандидата"], ["fsp", "Для Федерации спортивного программирования"]];
const WHO_SHORT: Record<Who, string> = { employer: "Работодателю", candidate: "Кандидату", fsp: "Федерации" };

const LAWS: { n: string; title: string; old: string; text: Record<Who, string> }[] = [
  {
    n: "01", title: "Доказательство вместо заявления", old: "«Senior, пять лет опыта» — на слово",
    text: {
      employer: "Вместо строчки в резюме — уровень по адаптивному тесту IRT с погрешностью и достижения из реестра ФСП. У каждого «почему этот кандидат» — ссылка на факт.",
      candidate: "Не нужно уметь продавать себя. Один раз подтвердите уровень тестом — категория «направление · грейд» говорит за вас.",
      fsp: "Результаты соревнований становятся карьерным активом: место из реестра ФСП — подтверждённый сигнал в профиле, а не строчка в резюме.",
    },
  },
  {
    n: "02", title: "Первым пишет работодатель", old: "Сотни откликов вслепую",
    text: {
      employer: "Опишите задачу своими словами — подборка с объяснением соберётся сама. Вы выходите на контакт первым, без разбора сотен нерелевантных резюме.",
      candidate: "Никаких откликов в пустоту. Компании находят вас по подтверждённой категории и приходят с приглашением.",
      fsp: "Спрос работодателей на навыки — в агрегатах кабинета ФСП: какие направления и уровни ищут и как соревнования влияют на приглашения.",
    },
  },
  {
    n: "03", title: "Деньги — в первом сообщении", old: "«Зарплата обсуждается на собеседовании»",
    text: {
      employer: "Вилка «от–до» в рублях обязательна в каждом приглашении: сильные кандидаты отвечают, когда условия ясны сразу.",
      candidate: "Зарплату вы видите до начала общения. Свою минимальную планку держите при себе — работодатель её не видит.",
      fsp: "Зарплаты из офферов на платформе — картина рынка по направлениям для федерации и участников; малые группы скрыты.",
    },
  },
  {
    n: "04", title: "Контакты — только с согласия", old: "Имя и телефон — всем, кто открыл резюме",
    text: {
      employer: "Обезличенный профиль: решение — по навыкам, а не по имени и возрасту. Требования проверяются по ст. 64 ТК РФ до публикации.",
      candidate: "Имя и контакты открываются, только когда вы приняли приглашение. Повторные приглашения от одной компании ограничены сроком.",
      fsp: "Федерации — только агрегаты без персональных данных: видно эффект соревнований, а не людей.",
    },
  },
];

export function DraftLaws() {
  const [who, setWho] = useState<Who>("employer");
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const k = (WHO.findIndex(([w]) => w === who) + d + WHO.length) % WHO.length;
    setWho(WHO[k][0]); refs.current[k]?.focus();
  }
  return (
    <section id="laws" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-20 sm:px-6 md:py-24" aria-labelledby="laws-title">
      <p className="np-eyebrow">Обратный драфт · манифест</p>
      <h2 id="laws-title" className="mt-4 max-w-3xl text-3xl font-extrabold leading-tight tracking-tight np-text md:text-[2.6rem]">
        Почему резюме больше не работает: <span className="np-grad">4 закона Драфта</span>
      </h2>
      <div role="tablist" aria-label="Чьими глазами" onKeyDown={onKey} className="np-seg mt-8">
        {WHO.map(([w, t], k) => (
          <button key={w} ref={(el) => { refs.current[k] = el; }} type="button" role="tab" id={`laws-tab-${w}`} aria-selected={who === w}
            aria-controls="laws-panel" tabIndex={who === w ? 0 : -1} onClick={() => setWho(w)} className="np-seg-btn">
            <span className="sm:hidden">{WHO_SHORT[w]}</span><span className="hidden sm:inline">{t}</span>
          </button>
        ))}
      </div>
      <div id="laws-panel" role="tabpanel" aria-labelledby={`laws-tab-${who}`} className="mt-6 grid gap-4 md:grid-cols-2">
        {LAWS.map((l) => (
          <article key={l.n} className="np-glass np-law p-6">
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-sm np-accent">{l.n}</span>
              <span className="np-old" aria-label={`Было: ${l.old}`}><s>{l.old}</s></span>
            </div>
            <h3 className="mt-4 text-xl font-bold tracking-tight np-text">{l.title}</h3>
            <p key={who} className="np-fade mt-2 text-sm leading-relaxed np-muted md:text-[0.95rem]">{l.text[who]}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

// ИИ-Адвокат зарплаты кандидата: письмо-обоснование встречного оффера на фактах «Драфта» —
// перцентиль IRT θ, закрытые дефицитные навыки hh.ru, паспорт ФСП (T2) и подпись Ed25519.
import { useState } from "react";
import { NB, Seg, catTitle, rub } from "./ui";
import { useAuth } from "../lib/auth";

type Ask = "10" | "15" | "20" | "25";
const ASKS: { id: Ask; title: string }[] = [
  { id: "10", title: "+10 %" }, { id: "15", title: "+15 %" }, { id: "20", title: "+20 %" }, { id: "25", title: "+25 %" },
];

// Факты профиля демо-кандидата; на живом профиле приходят из результата теста и паспорта.
const FACTS = {
  theta: 1.34, percentile: 91,
  skills: [{ name: "Kafka", share: 38 }, { name: "Kubernetes", share: 44 }, { name: "PostgreSQL: тюнинг запросов", share: 31 }],
  fsp: "1 спортивный разряд по спортивному программированию, призёр Кубка России по продуктовому программированию",
  key: "ed25519:3f9a…b71c",
  marketP75: 290_000,
};

/** Чем выше просьба, тем больше аргументов в письме: сила обоснования растёт вместе с запросом. */
function letter(ask: number, offer: number, company: string, category: string): string {
  const target = Math.round((offer * (1 + ask / 100)) / 5000) * 5000;
  const args = [
    `Подтверждённый уровень. Адаптивный тест (2PL IRT) дал θ = +${FACTS.theta.toLocaleString("ru-RU")} — это ${FACTS.percentile}-й перцентиль категории «${category}»: сильнее меня тест прошли ${100 - FACTS.percentile} % кандидатов.`,
    `Дефицитные навыки рынка. Я закрыл тестом навыки, которые hh.ru отмечает как дефицитные: ${FACTS.skills.map((s) => `${s.name} (в ${s.share} % вакансий)`).join(", ")}. Это сокращает мою адаптацию в вашей команде.`,
    ask >= 15 && `Спортивный паспорт ФСП (уровень доказательства T2): ${FACTS.fsp}. Это опыт решения задач в команде под жёстким дедлайном, подтверждённый федерацией, а не самооценкой.`,
    ask >= 20 && `Проверяемость. Результаты подписаны ключом ${FACTS.key} — вы можете проверить паспорт за минуту без запроса ко мне, а итог устной защиты кода подтверждает, что задачи решены без нейросетей.`,
    ask >= 25 && `Рынок. Верхний квартиль предложений для этой категории — ${rub(FACTS.marketP75)}; запрошенная сумма остаётся внутри рыночного коридора для кандидатов моего перцентиля.`,
  ].filter(Boolean).map((a, i) => `${i + 1}. ${a}`);
  return [
    `Здравствуйте!`,
    ``,
    `Спасибо за предложение${company ? ` от ${company}` : ""} и за интерес к моему профилю. Мне близки задачи команды, и я хочу договориться о сотрудничестве. Предлагаю обсудить вилку ${rub(target)} в месяц (+${ask}${NB}% к предложенным ${rub(offer)}). Обоснование:`,
    ``,
    ...args,
    ``,
    `Готов подтвердить уровень на техническом интервью или в коротком задании с вилкой. Буду рад договориться о встрече на этой неделе.`,
    ``,
    `С уважением,`,
    `кандидат «Драфта»`,
  ].join("\n");
}

export default function SalaryAdvocate({ embedded = false }: { embedded?: boolean }) {
  const { me } = useAuth();
  const c: any = (me as any)?.candidate;
  const catId = c?.current_category_id ?? c?.specializations?.find((s: any) => s.category_id)?.category_id;
  const category = catId ? catTitle(catId) : "Backend · Middle";
  const [ask, setAsk] = useState<Ask>("20");
  const [offer, setOffer] = useState(220_000);
  const [company, setCompany] = useState("");
  const [copied, setCopied] = useState(false);
  const text = letter(Number(ask), offer || 0, company.trim(), category);
  const strength = { "10": 72, "15": 84, "20": 93, "25": 88 }[ask];
  async function copy() {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); ta.remove();
    }
    setCopied(true); window.setTimeout(() => setCopied(false), 2000);
  }
  const body = (
    <>
      <div>
        <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand">ИИ-Адвокат зарплаты</p>
        <h2 className="mt-0.5 text-lg font-bold text-brand-night">Обоснование встречного оффера на ваших фактах</h2>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-semibold text-brand-night">Предложение работодателя, ₽/мес
          <input className="input mt-1" inputMode="numeric" value={offer ? offer.toLocaleString("ru-RU") : ""}
            onChange={(e) => setOffer(Number(e.target.value.replace(/\D/g, "")) || 0)} />
        </label>
        <label className="text-sm font-semibold text-brand-night">Компания <span className="font-normal text-brand-ink/55">(необязательно)</span>
          <input className="input mt-1" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="«Северный платёж»" />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-semibold text-brand-night">Желаемая прибавка</span>
        <Seg label="Желаемая прибавка" value={ask} onChange={(v) => { setAsk(v); setCopied(false); }} options={ASKS} />
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="chip">θ +{FACTS.theta.toLocaleString("ru-RU")} · {FACTS.percentile}-й перцентиль</span>
        <span className="chip">hh.ru: {FACTS.skills.length} дефицитных навыка</span>
        <span className="chip">ФСП · T2</span>
        <span className="chip">Ed25519 ✓</span>
      </div>
      <div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="font-semibold text-brand-night">Сила обоснования</span>
          <span className="font-bold tabular-nums text-brand-night">{strength}{NB}%</span>
        </div>
        <div className="mt-1 h-2 rounded-full bg-brand-night/10" aria-hidden="true">
          <div className={`h-2 rounded-full transition-all ${strength >= 85 ? "bg-emerald-600" : "bg-amber-500"}`} style={{ width: `${strength}%` }} />
        </div>
        {ask === "25" && <p className="mt-1 text-xs text-amber-700">+25 % — у верхней границы рынка: письмо опирается на верхний квартиль офферов.</p>}
      </div>
      <textarea aria-label="Письмо работодателю" readOnly className="input min-h-[340px] whitespace-pre-wrap text-xs leading-relaxed" value={text} />
      <div className="flex flex-wrap items-center justify-end gap-3">
        {copied && <span role="status" className="text-sm font-semibold text-emerald-700">✓ Скопировано</span>}
        <button type="button" className="btn-primary" onClick={copy} data-testid="salary-advocate-copy">Скопировать для ответа работодателю</button>
      </div>
    </>
  );
  if (embedded) return <div className="space-y-4" data-testid="salary-advocate">{body}</div>;
  return <section className="card space-y-4" aria-label="ИИ-Адвокат зарплаты" data-testid="salary-advocate">{body}</section>;
}

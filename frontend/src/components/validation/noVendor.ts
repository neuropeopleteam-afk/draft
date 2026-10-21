/**
 * Поставщики моделей на сайте не называются (общие правила проекта, решение владельца 21.10).
 * Данные /validation (ru_llm.json, strongest.json, llm_models.json, grader_check.json) хранят полные
 * идентификаторы для воспроизводимости — на экран они выходят только через эти функции:
 *  - modelAlias(): роль модели («модель стенда», «российская модель», «открытая модель на нашем сервере»)
 *    или нейтральная буква («модель А», «модель Б», …) в порядке первого появления в блоке;
 *  - noVendor(): замена названий в свободном тексте условий и пояснений.
 */

const LETTERS = "АБВГДЕЖИКЛМНПРСТУФХЦ";

const ROLE: [RegExp, string][] = [
  [/^rules$|правил/i, "Правила и словари (без модели)"],
  [/sonnet/i, "Модель стенда"],
  [/fable/i, "Вторая модель оценщика"],
  [/yandex/i, "Российская модель"],
  [/gpt-oss/i, "Открытая модель-эталон"],
  [/llm-local|qwen3?\.?5-9b|открытые веса|q4_k_m/i, "Открытая модель на нашем сервере"],
];

const VARIANT: Record<string, string> = { noreason15: "без рассуждений", "llm-local": "на нашем сервере" };

/** Фабрика: одна на блок, чтобы буквы были стабильны внутри таблицы. */
export function makeModelAlias(): (keyOrName: string | null | undefined) => string {
  const seen = new Map<string, string>();
  return (raw) => {
    const s = String(raw ?? "").trim();
    if (!s) return "—";
    // уже нейтральная подпись с сервера (validation/no_vendor.py): «модель стенда», «модель А» — как есть
    if (/[а-яё]/i.test(s)) return s.charAt(0).toUpperCase() + s.slice(1);
    const [base, variant] = s.split("@");
    let name = ROLE.find(([re]) => re.test(s))?.[1];
    if (!name) {
      const k = base.toLowerCase();
      if (!seen.has(k)) seen.set(k, `Модель ${LETTERS[seen.size % LETTERS.length]}`);
      name = seen.get(k)!;
    }
    const v = variant && !/llm-local/.test(variant) ? VARIANT[variant] ?? variant : null;
    return v ? `${name} (${v})` : name;
  };
}

const SUBS: [RegExp, string][] = [
  [/OpenRouter \(зарубежный провайдер\)/g, "зарубежный провайдер"],
  [/Yandex AI Studio/g, "российское облако"],
  [/OpenAI-совместимый API/g, "стандартный API"],
  [/LLM_CHAIN=yandex/g, "«только российская модель»"],
  [/YandexGPT[\s\d.]*\d|YandexGPT/g, "российская модель"],
  [/модели семейства Claude/g, "модели того же семейства"],
  [/Claude(?: Sonnet| Opus| Haiku| Fable)?[\s\d.]*\d|\bSonnet\b(?:[\s\d.]*\d)?|\bClaude\b/g, "модель стенда"],
  [/\bFable\s*[\d.]+/g, "вторая модель"],
  [/gpt-oss-120b/g, "открытая модель-эталон"],
  [/\b(?:xAI|Moonshot|Anthropic|OpenAI|Google|Alibaba|Zhipu)\s+/g, ""],
  [/\bQwen[\w.\-]*(?:\s+(?:[A-Z]?\d[\w.\-]*|Q4_K_M))*/g, "открытая модель"],
  [/\b(?:DeepSeek|Grok|Kimi|Gemini|GLM|GPT)[\w.\-]*(?:\s+(?:[A-Z]?\d[\w.\-]*|Flash|Pro|Mini))*/g, "модель другой компании"],
  [/\b(?:anthropic|openai|google|x-ai|moonshotai|deepseek|qwen|z-ai|yandex)\/[\w.\-@:]+/gi, "модель"],
  [/OpenRouter/g, "зарубежный провайдер"],
];

export function noVendor(text: string | null | undefined): string {
  let s = String(text ?? "");
  for (const [re, rep] of SUBS) s = s.replace(re, rep);
  return s;
}

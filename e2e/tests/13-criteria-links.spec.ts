/**
 * «Проверьте нас по критериям ТЗ» (/criteria, К1): страница открывается с главной, числа — из того же источника, что
 * API (GET /api/validation/criteria → расчёты /validation), и каждая ссылка страницы открывается и ведёт к видимому
 * блоку: якорь существует и оказывается на экране; ссылка с ролью входит в свою песочницу жюри (/jury/go) и
 * приводит на нужный экран; у ссылки на демо-потребность — её подборка. Первый сценарий заодно проверяет название «Драфт»
 * (/api/meta, вкладка, шапка, манифест).
 */
import { expect, test } from "../lib/fixtures";

const NB = "\u00a0";
const num = (v: number, d: number) => v.toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }).replace("-", "−");
const fmt = (v: number, f: string) =>
  f === "pct1" ? `${num(v * 100, 1)}${NB}%` : f === "pct" ? `${num(v * 100, 0)}${NB}%`
    : f === "signed3" ? `${v > 0 ? "+" : ""}${num(v, 3)}` : num(v, f === "num1" ? 1 : f === "num2" ? 2 : 3);

// Название продукта «Драфт», подзаголовок «Компании выбирают подтверждённых»; старого названия в видимом тексте нет
// («встречное предложение» кандидата — функция продукта, к названию не относится)
const OLD_NAME = /Встречн(ый|ого|ому|ым|ом)(?![а-яё])/;

test("главная → «Проверить по критериям ТЗ»: 6 критериев, блок «только здесь», числа из API; название «Драфт»", async ({ page }) => {
  expect((await (await page.request.get("/api/meta")).json()).product_name).toBe("Драфт");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveTitle("Драфт — компании выбирают подтверждённых");
  await expect(page.getByRole("main")).toContainText("Компании выбирают подтверждённых");
  await expect(page.locator('header [aria-label="Драфт — на главную"]').first()).toBeVisible();
  expect(await page.locator("body").innerText()).not.toMatch(OLD_NAME);
  const manifest = await (await page.request.get("/manifest.webmanifest")).json();
  expect(manifest.name).toMatch(/^Драфт — /);
  expect(manifest.short_name).toBe("Драфт");
  await page.locator("section#jury").getByRole("link", { name: "критерии ТЗ" }).click();  // SIMPLIFY п.9: строка «Для экспертов»
  await expect(page).toHaveURL(/\/criteria$/);
  await expect(page.getByRole("heading", { level: 1, name: "Проверьте нас по критериям ТЗ" })).toBeVisible();
  await expect(page.locator("section#unique").getByRole("heading", { name: "Что можно проверить только здесь" })).toBeVisible();
  const d = await (await page.request.get("/api/validation/criteria")).json();
  expect(d.criteria).toHaveLength(6);
  for (const c of d.criteria) {
    await expect(page.locator(`section#${c.id}`).getByRole("heading", { level: 2 })).toContainText(`${c.n}. ${c.title}`);
    await expect(page.locator(`section#${c.id} [data-testid=criteria-item]`)).toHaveCount(c.items.length);
  }
  // каждое число на странице — значение из API в формате интерфейса (на странице чисел не пишут)
  let metrics = 0;
  for (const c of d.criteria) for (const it of c.items) {
    if (it.proof.kind !== "metric") continue;
    metrics++;
    await expect(page.getByTestId(`proof-${it.id}`).getByTestId("criteria-value")).toHaveText(fmt(it.proof.value, it.proof.fmt));
    if (it.proof.signature?.commit && it.proof.signature.commit !== "не записан") {
      await expect(page.getByTestId(`proof-${it.id}`).getByTestId("criteria-signature")).toContainText(it.proof.signature.commit);
    }
  }
  expect(metrics).toBeGreaterThanOrEqual(7);
  // Я8 п. 5: у каждого доказательства — строка происхождения (вид данных из API), как у чисел /validation
  for (const c of d.criteria) for (const it of c.items) {
    if (!it.proof.provenance) continue;
    const line = page.getByTestId(`proof-${it.id}`).getByTestId("provenance-line");
    await expect(line).toHaveAttribute("data-kind", it.proof.provenance.kind);
    await expect(line).toContainText(it.proof.provenance.kind_label, { ignoreCase: true });
  }
});

// экраны, которые сами переводят дальше: «Сравнение» открывает сравнение первой потребности
const REDIRECT: Record<string, RegExp> = { "/employer/compare": /^\/employer\/needs\/[0-9a-f-]{36}\/compare$/ };

test("каждая ссылка /criteria открывается и ведёт к видимому блоку", async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await page.goto("/criteria", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("criteria-item").first()).toBeVisible();
  const links = await page.locator("[data-criteria-link]").evaluateAll((els) =>
    els.map((e) => ({ href: e.getAttribute("href") ?? "", to: e.getAttribute("data-criteria-link") ?? "" })));
  const uniq = [...new Map(links.map((l) => [l.href, l])).values()];
  expect(uniq.length).toBeGreaterThanOrEqual(30);
  const failed: string[] = [];
  for (const { href, to } of uniq) {
    const [path, hash] = to.split("#");
    const step = `${href} → ${to}`;
    try {
      // каждая ссылка — с чистой загрузки, как из новой вкладки (иначе якорь прошлой ссылки /validation ещё удерживается)
      await page.goto("about:blank");
      if (path.startsWith("/api/")) {
        const r = await page.goto(href, { waitUntil: "domcontentloaded" });
        expect(r?.ok(), step).toBeTruthy();
        if (path === "/api/docs") await expect(page.locator("#swagger-ui"), step).toBeVisible();
        continue;
      }
      await page.goto(href, { waitUntil: "domcontentloaded" });
      const need = new URL(href, "http://x").searchParams.get("need");
      const want = need ? /\/employer\/needs\/[0-9a-f-]{36}$/ : REDIRECT[path] ?? new RegExp(`^${path.split("?")[0].replace(/\/$/, "") || ""}/?$`);
      await expect.poll(() => new URL(page.url()).pathname, { message: step, timeout: 60_000 }).toMatch(want);
      if (hash) {
        const el = page.locator(`[id="${hash}"]`).first();
        await expect(el, step).toBeVisible({ timeout: 30_000 });
        await expect(el, step).toBeInViewport({ timeout: 15_000 });
      } else {
        await expect(page.locator("main h1, main h2, h1").first(), step).toBeVisible({ timeout: 30_000 });
      }
      await expect(page.getByText("Такой страницы нет"), step).toHaveCount(0);
    } catch (e) {
      failed.push(`${step}: ${String(e).replace(/\u001b\[\d+m/g, "").replace(/\s+/g, " ").replace(step, "").slice(0, 400)}`);
    }
  }
  expect(failed, failed.join("\n")).toEqual([]);
});

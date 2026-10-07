const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const assert = require("assert/strict");

const root = path.resolve(__dirname, "../..");
const out = path.join(root, "docs/realdata");
const origin = "http://127.0.0.1:5108";

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(90000);
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  const results = [];
  for (const format of ["json", "csv"]) {
    const response = await context.request.get(`${origin}/api/validation/closed-set/template/${format}`);
    assert.equal(response.status(), 200);
    fs.writeFileSync(path.join(out, `closed-set-template.${format}`), await response.body());
  }
  await page.goto(`${origin}/validation`);
  await page.locator("#closed-set").scrollIntoViewIfNeeded();
  await page.locator('#closed-set input[type="file"]').setInputFiles(path.join(out, "closed-set-template.json"));
  await page.getByRole("button", { name: "Проверить набор в своей песочнице" }).click();
  await page.locator('#closed-set [aria-live="polite"]').waitFor();
  assert.match(await page.locator("#closed-set").innerText(), /20,0\s*%/);
  assert.match(await page.locator("#closed-set").innerText(), /не проверены платформой/);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать выдачу CSV" }).click();
  const download = await downloadPromise;
  await download.saveAs(path.join(out, "browser_closed_set_results.csv"));
  assert.match(fs.readFileSync(path.join(out, "browser_closed_set_results.csv"), "utf8"), /explanations/);
  const guideHide = page.getByRole("button", { name: "Скрыть", exact: true });
  if (await guideHide.count()) await guideHide.click();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.locator('#closed-set [aria-live="polite"]').scrollIntoViewIfNeeded();
    const dimensions = await page.evaluate(() => ({
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    }));
    assert(dimensions.scrollWidth <= dimensions.width, JSON.stringify(dimensions));
    await page.screenshot({ path: path.join(out, `closed-set-${width}.png`) });
    results.push({ screen: "closed-set-results", ...dimensions, passed: true });
  }
  await page.getByRole("button", { name: "Очистить данные" }).click();
  assert.equal(await page.locator('#closed-set [aria-live="polite"]').count(), 0);
  await page.locator('#closed-set input[type="file"]').setInputFiles(path.join(out, "closed-set-template.csv"));
  await page.getByRole("button", { name: "Проверить набор в своей песочнице" }).click();
  await page.locator('#closed-set [aria-live="polite"]').waitFor();
  assert.match(await page.locator("#closed-set").innerText(), /20,0\s*%/);
  await page.reload();
  assert.equal(await page.locator('#closed-set [aria-live="polite"]').count(), 0);
  await page.goto(`${origin}/employer/needs`);
  await page.locator("textarea#need").fill("Android developer middle: обязательно Kotlin и REST API. Гибрид в Москве.");
  await page.getByRole("button", { name: "Разобрать требования" }).click();
  await page.getByText(/Отдельной категории «Мобильная разработка»/).waitFor();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const dimensions = await page.evaluate(() => ({
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    }));
    assert(dimensions.scrollWidth <= dimensions.width, JSON.stringify(dimensions));
    await page.locator("textarea#need").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, `unsupported-mobile-${width}.png`) });
    results.push({ screen: "unsupported-mobile", ...dimensions, passed: true });
  }
  assert.equal(errors.length, 0, JSON.stringify(errors));
  fs.writeFileSync(path.join(out, "browser_check.json"),
                   JSON.stringify({ results, errors, json_upload: true, csv_upload: true,
                                    csv_export: true, clear_and_reload: true }, null, 2));
  console.log(JSON.stringify(results));
  await browser.close();
})().catch(e => { console.error(e); process.exitCode = 1; });

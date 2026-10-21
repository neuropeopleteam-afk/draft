// Презентация «Драфт» для жюри спецтрека ФСП: PPTX (редактируемый) + PDF.
// Цифры — только из docs/submission/out/facts.json (собирает docs/submission/build.py из docs/NUMBERS.json).
// Запуск: node docs/presentation/build.mjs (обычно из build.py). PDF — LibreOffice (soffice).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const pptxgen = require('pptxgenjs');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const A = (f) => path.join(HERE, 'assets', f);
const FACTS = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs/submission/out/facts.json'), 'utf8'));
const F = FACTS.facts;
const R = FACTS.repo;
const PAIRS = FACTS.pairs || { pairs: [], real: [] };
const SITE = 'fsp-draft.ru';
const PENDING = 'после итогового прогона';

// ---------- палитра и шрифты (как на сайте: Montserrat, индиго и красный) ----------
const C = { white: 'FFFFFF', text: 'F3F4FF', muted: 'C9CCF2', faint: '9EA3D9', red: 'EC1D35', indigo: '402FFF',
  lav: 'A59DFF', ok: '4BE3A3', card: 'FFFFFF', dark: '0A0B1F' };
const FONT = 'Montserrat';

const fv = (id) => (F[id] ? F[id].text : null);
const has = (...ids) => ids.every((i) => F[i]);

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE'; // 13,333 × 7,5 дюйма
pptx.author = 'Команда Neuropeople';
pptx.company = 'команда Neuropeople';
pptx.title = '«Драфт» — найм IT-специалистов с подтверждённым грейдом';

let N = 0;
function base(tag, { bg = 'bg_content.jpg' } = {}) {
  const s = pptx.addSlide();
  N += 1;
  s.background = { path: A(bg) };
  s.addImage({ path: A('logos_organizers.png'), x: 7.65, y: 0.36, w: 5.34, h: 0.37 });
  if (tag) {
    const w = 0.42 + tag.length * 0.115;
    s.addShape(pptx.ShapeType.roundRect, { x: 0.45, y: 0.33, w, h: 0.44, fill: { color: C.red }, line: { color: C.red }, rectRadius: 0.12 });
    s.addText(tag.toUpperCase(), { x: 0.45, y: 0.33, w, h: 0.44, fontFace: FONT, fontSize: 11, bold: true, color: C.white, align: 'center', valign: 'middle', margin: 0 });
  }
  s.addImage({ path: A('logo_fsp.png'), x: 0.45, y: 7.0, w: 2.37, h: 0.3 });
  s.addShape(pptx.ShapeType.rect, { x: 3.0, y: 7.0, w: 0.02, h: 0.3, fill: { color: C.faint }, line: { color: C.faint } });
  s.addText([{ text: 'Драфт', options: { bold: true } }, { text: `   ${SITE}`, options: { color: C.muted } }],
    { x: 3.15, y: 6.95, w: 3.5, h: 0.4, fontFace: FONT, fontSize: 11, color: C.white, valign: 'middle', margin: 0 });
  s.addText(String(N), { x: 12.3, y: 6.95, w: 0.6, h: 0.4, fontFace: FONT, fontSize: 11, color: C.muted, align: 'right', valign: 'middle', margin: 0 });
  return s;
}
function title(s, text, { y = 0.95, size = 30, w = 12.4 } = {}) {
  s.addText(text, { x: 0.45, y, w, h: 1.05, fontFace: FONT, fontSize: size, bold: true, color: C.white, valign: 'top', margin: 0, lineSpacingMultiple: 0.95 });
}
function sub(s, text, { y = 2.0, w = 12.4, size = 15, h = 0.6 } = {}) {
  s.addText(text, { x: 0.45, y, w, h, fontFace: FONT, fontSize: size, color: C.muted, valign: 'top', margin: 0 });
}
function card(s, x, y, w, h, { fill = C.card, transparency = 90, line = 'FFFFFF', lineT = 75 } = {}) {
  s.addShape(pptx.ShapeType.roundRect, { x, y, w, h, fill: { color: fill, transparency }, line: { color: line, transparency: lineT, width: 0.75 }, rectRadius: 0.14 });
}
function cardText(s, x, y, w, h, head, body, { headSize = 15, bodySize = 12, accent = null } = {}) {
  card(s, x, y, w, h);
  if (accent) s.addShape(pptx.ShapeType.rect, { x: x + 0.22, y: y + 0.24, w: 0.42, h: 0.06, fill: { color: accent }, line: { color: accent } });
  const top = accent ? 0.38 : 0.2;
  s.addText(head, { x: x + 0.22, y: y + top, w: w - 0.44, h: 0.5, fontFace: FONT, fontSize: headSize, bold: true, color: C.white, valign: 'top', margin: 0 });
  s.addText(body, { x: x + 0.22, y: y + top + 0.5, w: w - 0.44, h: h - top - 0.65, fontFace: FONT, fontSize: bodySize, color: C.text, valign: 'top', margin: 0, paraSpaceAfter: 3 });
}
function bigNum(s, x, y, w, value, label, { size = 30, color = C.white } = {}) {
  s.addText(value ?? PENDING, { x, y, w, h: 0.6, fontFace: FONT, fontSize: value ? size : 11, bold: !!value, color: value ? color : C.faint, valign: 'bottom', margin: 0 });
  s.addText(label, { x, y: y + 0.62, w, h: 0.62, fontFace: FONT, fontSize: 11, color: C.muted, valign: 'top', margin: 0 });
}
function note(s, text, { x = 0.45, y = 6.42, w = 12.4, h = 0.45, size = 9.5 } = {}) {
  s.addText(text, { x, y, w, h, fontFace: FONT, fontSize: size, color: C.faint, valign: 'top', margin: 0 });
}
const bullets = (arr, opt = {}) => arr.map((t) => ({ text: t, options: { bullet: { indent: 14 }, paraSpaceAfter: 5, ...opt } }));

// ===================== ВЫСТУПЛЕНИЕ: 7 слайдов на ≈2,5 мин (текст — docs/presentation/PITCH.md) =====================
// Дальше — приложение для вопросов жюри (прежние слайды 2–12). Цифры — те же facts.json; нет цифры — «после итогового прогона».
const pair = (id) => PAIRS.pairs.find((p) => p.id === id) || { label: id };
const realv = (id) => PAIRS.real.find((r) => r.id === id) || { label: id };
function numCell(s, x, y, w, v, { size = 26, color = C.white } = {}) {
  s.addText(v ? v.text : PENDING, { x, y, w, h: 0.55, fontFace: FONT, fontSize: v ? size : 11, bold: !!v, color: v ? color : C.faint, valign: 'middle', margin: 0 });
}

// ---------- В1. Титул: команда, задача, логотип ФСП (макет шаблона организаторов, слайд 7) ----------
{
  const s = pptx.addSlide();
  N += 1;
  s.background = { path: A('bg_title.jpg') };
  s.addImage({ path: A('logo_fsp.png'), x: 0.45, y: 0.62, w: 4.4, h: 0.556 });
  s.addImage({ path: A('logo_draft.png'), x: 0.75, y: 1.95, w: 3.6, h: 1.148 });
  s.addText('Компании выбирают подтверждённых', { x: 0.45, y: 3.3, w: 9.6, h: 0.65, fontFace: FONT, fontSize: 30, bold: true, color: C.white, margin: 0, fit: 'shrink' });
  s.addText('Найм IT-специалистов наоборот: уровень ставит тест, а компания сама приходит к кандидату — с зарплатой в приглашении.',
    { x: 0.45, y: 4.05, w: 7.6, h: 0.8, fontFace: FONT, fontSize: 15, color: C.text, margin: 0, valign: 'top' });
  s.addText('ЗАДАЧА', { x: 0.45, y: 5.0, w: 3.0, h: 0.3, fontFace: FONT, fontSize: 10, bold: true, color: 'FF8A98', margin: 0, charSpacing: 1 });
  s.addText('Цифровая платформа-агрегатор ИТ-вакансий с верифицированным профилем достижений участника Федерации спортивного программирования (ФСП)',
    { x: 0.45, y: 5.3, w: 8.2, h: 0.75, fontFace: FONT, fontSize: 13.5, bold: true, color: C.white, margin: 0, valign: 'top' });
  s.addText([{ text: 'Команда Neuropeople', options: { bold: true } }, { text: '  ·  капитан Денис Михеев  ·  ' }, { text: SITE, options: { bold: true, hyperlink: { url: `https://${SITE}` } } }],
    { x: 0.45, y: 6.25, w: 9.5, h: 0.4, fontFace: FONT, fontSize: 14, color: C.white, margin: 0 });
  s.addText('Специальный трек ФСП · Лидеры цифровой трансформации 2026', { x: 0.45, y: 6.68, w: 9.5, h: 0.35, fontFace: FONT, fontSize: 11, color: C.muted, margin: 0 });
}

// ===================== ОБЯЗАТЕЛЬНЫЙ БЛОК организаторов (шаблон, слайды 8–11) =====================
// Пропуски, которые сообщит владелец, — заметная пометка TBD; после получения фактов — подставить и пересобрать.
const TBD = '—\u00a0уточняется\u00a0—';
C.warn = 'FFC94D';
const tbd = (o = {}) => ({ text: TBD, options: { color: C.warn, bold: true, ...o } });
// абзац из нескольких фрагментов: свойства абзаца — у первого фрагмента, конец — breakLine
function para(runs, { bullet = true, indentLevel = 0, after = 6 } = {}) {
  const rr = runs.map((r) => (typeof r === 'string' ? { text: r, options: {} } : { text: r.text, options: { ...(r.options || {}) } }));
  Object.assign(rr[0].options, { paraSpaceAfter: after, ...(bullet ? { bullet: { indent: 14 }, indentLevel } : {}) });
  rr[rr.length - 1].options.breakLine = true;
  return rr;
}
const B = (t) => ({ text: t, options: { bold: true, color: C.white } });
function head(s, x, y, w, text, color = C.white) {
  s.addText(text, { x, y, w, h: 0.4, fontFace: FONT, fontSize: 15, bold: true, color, margin: 0, valign: 'top' });
  s.addShape(pptx.ShapeType.rect, { x, y: y + 0.44, w: 0.42, h: 0.05, fill: { color: C.red }, line: { color: C.red } });
}

// ---------- О1. О команде и решении (шаблон, слайд 8) ----------
{
  const s = base('О команде и решении');
  title(s, 'Команда Neuropeople и решение «Драфт»', { size: 26 });
  card(s, 0.45, 1.75, 5.55, 4.55);
  head(s, 0.7, 1.95, 5.0, 'О команде');
  s.addText([
    ...para([B('Капитан: '), 'Денис Михеев, ', tbd()]),
    ...para([B('Количество участников: '), tbd()]),
    ...para([B('Краткое описание: '), 'команда Neuropeople, оператор платформы — команда Neuropeople'], { after: 3 }),
    ...para(['как образовалась команда: ', tbd()], { indentLevel: 1, after: 3 }),
    ...para(['место работы / учёбы: ', tbd()], { indentLevel: 1 }),
    ...para([B('Город и регион: '), tbd()]),
  ], { x: 0.7, y: 2.62, w: 5.1, h: 3.5, fontFace: FONT, fontSize: 13.5, color: C.text, margin: 0, valign: 'top' });

  card(s, 6.2, 1.75, 6.65, 2.5);
  head(s, 6.45, 1.95, 6.1, 'Краткое описание решения', C.white);
  s.addText('«Драфт» — платформа подбора ИТ-специалистов с обратной механикой. Кандидат проходит адаптивный тест и получает подтверждённый грейд. Работодатель описывает потребность текстом или голосом ИИ-проводнику Насте, видит подборку только из проверенных и сам приходит к кандидату с приглашением и обязательной зарплатной вилкой. Достижения ФСП — из официальных протоколов, в карточке со ссылкой.',
    { x: 6.45, y: 2.55, w: 6.2, h: 1.6, fontFace: FONT, fontSize: 11.5, color: C.text, margin: 0, valign: 'top' });

  card(s, 6.2, 4.4, 6.65, 1.9);
  head(s, 6.45, 4.55, 6.1, 'Уникальность решения', C.white);
  s.addText([
    ...para(['уровень ставит тест, а не резюме'], { after: 2 }),
    ...para(['каждая цифра — в двух колонках: стандартные условия и проверка на прочность; протокол и хэш — до прогона, прогон один'], { after: 2 }),
    ...para(['ИИ-проводник голосом ведёт по продукту и проводит устный этап теста'], { after: 2 }),
    ...para(['кабинет ФСП: спрос работодателей, карта талантов, протоколы'], { after: 0 }),
  ], { x: 6.45, y: 5.12, w: 6.2, h: 1.12, fontFace: FONT, fontSize: 11, color: C.text, margin: 0, valign: 'top' });
}

// ---------- О2. Участники (шаблон, слайд 9) ----------
{
  const s = base('Участники');
  title(s, 'Участники команды', { size: 26 });
  const TEAM = [
    { name: 'Денис Михеев', photo: 'team_mikheev.jpg', rows: [['Роль в команде', ['капитан · ', tbd()]], ['Ник в мессенджере', [tbd()]], ['Номер телефона', [tbd()]], ['Место работы / учёбы', [tbd()]]] },
    { name: 'Дмитрий Кузнецов', photo: 'team_kuznetsov.jpg', rows: [['Роль в команде', ['инженер по качеству и внедрению']], ['Ник в мессенджере', [tbd()]], ['Номер телефона', [tbd()]], ['Место работы / учёбы', [tbd()]]] },
  ];
  const PH = 1000 / 1070; // высота фото / ширина
  if (TEAM.length <= 2) {
    const cw = (12.4 - 0.25) / 2, ch = 3.95, y = 1.9;
    TEAM.forEach((m, i) => {
      const x = 0.45 + i * (cw + 0.25);
      card(s, x, y, cw, ch);
      const pw = 2.9, ph = pw * PH;
      s.addImage({ path: A(m.photo), x: x + 0.25, y: y + 0.25, w: pw, h: ph });
      const tx = x + 0.25 + pw + 0.3, tw = cw - pw - 0.8;
      s.addText(m.name, { x: tx, y: y + 0.22, w: tw, h: 0.42, fontFace: FONT, fontSize: 18, bold: true, color: C.white, margin: 0, valign: 'top', fit: 'shrink' });
      s.addShape(pptx.ShapeType.rect, { x: tx, y: y + 0.7, w: 0.42, h: 0.05, fill: { color: C.red }, line: { color: C.red } });
      m.rows.forEach(([lab, val], k) => {
        const ry = y + 0.9 + k * 0.72;
        s.addText(lab, { x: tx, y: ry, w: tw, h: 0.26, fontFace: FONT, fontSize: 9.5, color: C.muted, margin: 0, valign: 'top' });
        s.addText(val.map((v) => (typeof v === 'string' ? { text: v } : v)), { x: tx, y: ry + 0.25, w: tw, h: 0.44, fontFace: FONT, fontSize: 12, color: C.white, margin: 0, valign: 'top' });
      });
    });
  } else {
    const n = TEAM.length, gap = 0.15, cw = (12.4 - gap * (n - 1)) / n, y = 1.75, ch = 4.55;
    TEAM.forEach((m, i) => {
      const x = 0.45 + i * (cw + gap);
      card(s, x, y, cw, ch);
      const pw = cw - 0.4;
      s.addImage({ path: A(m.photo), x: x + 0.2, y: y + 0.2, w: pw, h: pw * PH });
      const ty = y + 0.3 + pw * PH;
      s.addText(m.name, { x: x + 0.2, y: ty, w: pw, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.white, margin: 0, fit: 'shrink' });
      s.addText(m.rows.flatMap(([lab, val]) => para([{ text: lab + ': ', options: { color: C.muted } }, ...val.map((v) => (typeof v === 'string' ? { text: v } : v))], { after: 2 })),
        { x: x + 0.2, y: ty + 0.42, w: pw, h: ch - (ty - y) - 0.55, fontFace: FONT, fontSize: 9, color: C.white, margin: 0, valign: 'top' });
    });
  }
}

// ---------- О3. История команды, выбор задачи, сложности (шаблон, слайд 10) ----------
{
  const s = base('История и вызовы');
  title(s, 'История команды, выбор задачи и сложности', { size: 26 });
  const hr = (y) => s.addShape(pptx.ShapeType.line, { x: 0.45, y, w: 12.4, h: 0, line: { color: C.red, width: 1 } });
  const num = (y, t) => s.addText(t, { x: 11.85, y, w: 1.0, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: C.red, margin: 0, align: 'right', valign: 'top' });
  hr(1.65); num(1.75, '01');
  s.addText('Краткая история команды', { x: 0.45, y: 1.75, w: 9, h: 0.35, fontFace: FONT, fontSize: 14, bold: true, color: C.white, margin: 0 });
  s.addText([tbd()], { x: 0.45, y: 2.12, w: 11.2, h: 0.35, fontFace: FONT, fontSize: 12, color: C.text, margin: 0, valign: 'top' });
  hr(2.62); num(2.72, '02');
  s.addText('Почему мы выбрали эту задачу', { x: 0.45, y: 2.72, w: 9, h: 0.35, fontFace: FONT, fontSize: 14, bold: true, color: C.white, margin: 0 });
  s.addText('Найм в ИТ держится на резюме, которые пишут все, а доказательств в них нет. Задача ФСП даёт шанс соединить проверяемые достижения спортсменов с реальным спросом работодателей. Нам была интересна именно «обратная» механика: компания сама приходит к кандидату, чей уровень подтверждён.',
    { x: 0.45, y: 3.1, w: 11.2, h: 0.75, fontFace: FONT, fontSize: 12, color: C.text, margin: 0, valign: 'top' });
  hr(3.98); num(4.08, '03');
  s.addText('Основные сложности и как мы с ними справились', { x: 0.45, y: 4.08, w: 9, h: 0.35, fontFace: FONT, fontSize: 14, bold: true, color: C.white, margin: 0 });
  const ch = [
    ['Честная проверка качества без людей', 'модельные кандидаты; протокол и хэш данных — до прогона; один прогон на отложенных мирах', C.red],
    ['Голосовой ИИ-проводник в реальном времени', 'задержки ответа, естественность речи, устный этап теста тем же голосом', C.lav],
    ['Распознавание протоколов ФСП', `в индексе ${fv('fsp_documents') ?? PENDING} официальных протоколов и ${fv('fsp_results') ?? PENDING} результатов спортсменов`, C.ok],
    ['Адаптивный тест с античитом', `видов сигналов честности — ${fv('ac_signals') ?? PENDING}; при подозрении — дополнительная проверка, без автоблокировок`, C.indigo],
  ];
  ch.forEach(([h, b, col], i) => cardText(s, 0.45 + i * 3.13, 4.55, 2.95, 1.72, h, b, { headSize: 12, bodySize: 10.5, accent: col }));
  note(s, 'Цифры — docs/NUMBERS.json: fsp_protocols.index.documents, fsp_protocols.index.results, anticheat.proctoring_signals_total.', { y: 6.42 });
}

// ---------- О4. Коротко о решении (шаблон, слайд 11) ----------
{
  const s = base('Коротко о решении');
  title(s, 'Техническая и маркетинговая суть решения', { size: 26 });
  const p5 = pair('p5');
  const tech = [
    [B('Стек: '), 'FastAPI и PostgreSQL, React и TypeScript, Docker Compose — запуск одной командой'],
    [B('Адаптивный тест: '), 'IRT, последовательное правило SPRT, второй этап у границы грейда'],
    [B('Банк: '), `${fv('bank_families') ?? PENDING} семейств заданий; код проверяется тестами на сервере, ключи в браузер не уходят`],
    [B('Подбор по подтверждённым фактам (LTR): '), `точность первой пятёрки ${p5.standard ? p5.standard.text : PENDING} в стандартных условиях и ${p5.hard ? p5.hard.text : PENDING} в проверке на прочность; у каждой карточки — «почему выше»`],
    [B('Индекс протоколов ФСП: '), `${fv('fsp_documents') ?? PENDING} протоколов, ${fv('fsp_results') ?? PENDING} результатов`],
    [B('ИИ-проводник «Настя»: '), 'речь ↔ речь, живой аватар; ведёт по продукту и проводит устный этап'],
  ];
  const mkt = [
    [B('Модель: '), 'кандидатам — бесплатно, работодатели платят за подтверждённый найм'],
    [B('Партнёрство с ФСП: '), 'канал к работодателям и региональным представительствам федерации'],
    [B('Интеграции: '), 'hh.ru и ATS работодателя — без смены привычных инструментов'],
    [B('План: '), 'калибровка заданий на ответах людей — в плане, не проведена: 300–500 участников, 6–8 недель, протокол — до начала'],
    [B('Дальше: '), 'практические задания на языке стека кандидата — Java, Kotlin, Go'],
  ];
  [[tech, 'Техническая суть решения', 0.45], [mkt, 'Маркетинговая суть решения', 6.75]].forEach(([items, h, x]) => {
    card(s, x, 1.75, 6.1, 4.55);
    head(s, x + 0.25, 1.95, 5.6, h);
    s.addText(items.flatMap((r) => para(r, { after: 9 })), { x: x + 0.25, y: 2.65, w: 5.6, h: 3.55, fontFace: FONT, fontSize: 12.5, color: C.text, margin: 0, valign: 'top' });
  });
  note(s, 'Цифры — docs/NUMBERS.json: bank.families; matching.p5 и matching.hard.p5 (модельные кандидаты, не люди); fsp_protocols.index.documents и .results.', { y: 6.42 });
}

// ---------- В2. Проблема ----------
{
  const s = base('Проблема');
  title(s, 'Резюме пишут все.\nДоказательств в нём нет', { size: 34 });
  s.addImage({ path: A('deco_cube.png'), x: 9.9, y: 0.95, w: 2.4, h: 2.4 });
  const y = 3.0, h = 2.9, w = 3.95;
  cardText(s, 0.45, y, w, h, 'Компания', 'Сотни откликов вручную, навыки ничем не подтверждены. Ошибка найма стоит месяцы.', { accent: C.red, headSize: 18, bodySize: 15 });
  cardText(s, 0.45 + w + 0.22, y, w, h, 'Кандидат', 'Откликается вслепую: зарплату и условия узнаёт только на собеседовании.', { accent: C.lav, headSize: 18, bodySize: 15 });
  cardText(s, 0.45 + 2 * (w + 0.22), y, w, h, 'Федерация ФСП', 'Объективные результаты спортсменов есть — канала к работодателям нет.', { accent: C.ok, headSize: 18, bodySize: 15 });
}

// ---------- В3. Решение: обратный драфт ----------
{
  const s = base('Решение');
  title(s, 'Обратный драфт: уровень ставит\nтолько тест, компания приходит сама', { size: 30 });
  const steps = [
    ['Тест вместо резюме', 'кандидат один раз подтверждает уровень', C.red],
    ['Категория', '«направление · грейд» — только по тесту', C.red],
    ['Задача своими словами', 'компания пишет или надиктовывает потребность', C.indigo],
    ['Подборка с объяснением', 'почему кандидат здесь и чем это подтверждено', C.indigo],
    ['Приглашение с вилкой', 'зарплата обязательна, контакты — после согласия', C.indigo],
  ];
  const w = 2.3, gap = 0.225;
  steps.forEach(([h, b, col], i) => {
    const x = 0.45 + i * (w + gap), y = 2.6;
    card(s, x, y, w, 3.0);
    s.addShape(pptx.ShapeType.ellipse, { x: x + 0.22, y: y + 0.25, w: 0.55, h: 0.55, fill: { color: col }, line: { color: C.white, transparency: 60 } });
    s.addText(String(i + 1), { x: x + 0.22, y: y + 0.25, w: 0.55, h: 0.55, fontFace: FONT, fontSize: 16, bold: true, color: C.white, align: 'center', valign: 'middle', margin: 0 });
    s.addText(h, { x: x + 0.22, y: y + 0.95, w: w - 0.4, h: 0.8, fontFace: FONT, fontSize: 16, bold: true, color: C.white, valign: 'top', margin: 0 });
    s.addText(b, { x: x + 0.22, y: y + 1.8, w: w - 0.4, h: 1.1, fontFace: FONT, fontSize: 13, color: C.text, valign: 'top', margin: 0 });
    if (i < steps.length - 1) s.addShape(pptx.ShapeType.line, { x: x + w, y: y + 0.52, w: gap, h: 0, line: { color: C.lav, width: 1.5, endArrowType: 'triangle' } });
  });
  s.addText('КАНДИДАТ', { x: 0.45, y: 5.72, w: 4.8, h: 0.35, fontFace: FONT, fontSize: 11, bold: true, color: 'FF8A98', margin: 0, align: 'center' });
  s.addText('РАБОТОДАТЕЛЬ', { x: 0.45 + 2 * (w + gap), y: 5.72, w: 3 * w + 2 * gap, h: 0.35, fontFace: FONT, fontSize: 11, bold: true, color: C.lav, margin: 0, align: 'center' });
  note(s, 'Резюме и заявленные навыки на место в подборке не влияют. Кандидат без истории ФСП ничего не теряет.', { y: 6.3 });
}

// ---------- В4. Тест ----------
{
  const s = base('Тестирование');
  title(s, 'Тест: свой вариант у каждого,\nв финале — разговор с ИИ-аватаром', { size: 30 });
  s.addImage({ path: A('deco_medal.png'), x: 10.3, y: 0.9, w: 2.3, h: 2.3 });
  bigNum(s, 0.45, 2.2, 3.1, fv('bank_families'), 'семейств заданий: генераторы, а не готовые вопросы', { size: 34 });
  bigNum(s, 3.7, 2.2, 3.1, fv('bank_variants'), 'уникальных вариантов на проверке банка', { size: 34 });
  bigNum(s, 6.95, 2.2, 3.1, fv('bank_checks_failed'), 'ошибок в ключах: варианты с кодом проверены исполнением', { size: 34 });
  const items = [
    ['Адаптивный', 'Следующее задание — по прошлым ответам; тест останавливается, когда уверенности достаточно.', C.red],
    ['Свои задания', 'Вариант собирается для кандидата; слив почти не помогает, ключи — только на сервере.', C.lav],
    ['Три исхода', 'Подтверждён · не подтверждён · у самой границы — короткий второй этап вместо угадывания.', C.ok],
    ['Финальный разговор', 'ИИ-аватар голосом спрашивает кандидата о его же решениях — дополнительная проверка.', C.indigo],
  ];
  items.forEach(([h, b, col], i) => cardText(s, 0.45 + i * 3.13, 3.85, 2.95, 2.35, h, b, { headSize: 15, bodySize: 12, accent: col }));
  note(s, 'Метод — байесовская последовательная классификация с остановкой по SPRT.', { y: 6.35 });
}

// ---------- В5. Подбор ----------
{
  const s = base('Подбор');
  title(s, 'Подборка — только из проверенного,\nи объяснение у каждого кандидата', { size: 30 });
  const rules = [
    ['Грейд — только подтверждённый тестом', 'заявленный в резюме уровень не фильтрует и не даёт баллов'],
    ['Навык без теста — ноль', 'место задают тест по навыкам этой вакансии и достижения ФСП'],
    ['ФСП — по официальным протоколам', 'бонус за подтверждённое, без штрафа тем, у кого истории нет'],
    ['«Почему он выше следующего»', 'объяснение полными фразами в каждой карточке'],
  ];
  rules.forEach(([h, b], i) => {
    const y = 2.35 + i * 0.98;
    card(s, 0.45, y, 7.3, 0.86);
    s.addText(h, { x: 0.7, y: y + 0.08, w: 6.9, h: 0.38, fontFace: FONT, fontSize: 15, bold: true, color: C.white, margin: 0 });
    s.addText(b, { x: 0.7, y: y + 0.45, w: 6.9, h: 0.35, fontFace: FONT, fontSize: 12, color: C.text, margin: 0 });
  });
  const p5 = pair('p5'), ext = realv('external');
  card(s, 8.0, 2.35, 4.85, 3.82);
  s.addText(p5.label || 'Подбор', { x: 8.25, y: 2.5, w: 4.4, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.white, margin: 0 });
  s.addText('стандартные условия', { x: 8.25, y: 2.95, w: 2.2, h: 0.3, fontFace: FONT, fontSize: 10, color: C.muted, margin: 0 });
  s.addText('проверка на прочность', { x: 10.5, y: 2.95, w: 2.3, h: 0.3, fontFace: FONT, fontSize: 10, color: 'FF8A98', margin: 0 });
  numCell(s, 8.25, 3.25, 2.2, p5.standard);
  numCell(s, 10.5, 3.25, 2.2, p5.hard);
  s.addShape(pptx.ShapeType.line, { x: 8.25, y: 4.05, w: 4.35, h: 0, line: { color: C.white, transparency: 75, width: 0.75 } });
  s.addText(ext.label || 'Внешний набор', { x: 8.25, y: 4.2, w: 4.4, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.ok, margin: 0 });
  numCell(s, 8.25, 4.6, 4.4, ext.value);
  s.addText('данные, которых при настройке не было', { x: 8.25, y: 5.2, w: 4.4, h: 0.5, fontFace: FONT, fontSize: 10, color: C.muted, margin: 0, valign: 'top' });
}

// ---------- В6. Честная проверка ----------
{
  const s = base('Валидация');
  title(s, 'Каждая цифра — дважды: в стандартных\nусловиях и в проверке на прочность', { size: 28 });
  const rows = ['exact_grade', 'false_confirm_all', 'ndcg10'].map(pair);
  const X = [0.45, 5.6, 8.1], TW = 10.6;
  card(s, 0.45, 2.2, TW, 0.62, { transparency: 85 });
  s.addText('Метрика', { x: X[0] + 0.25, y: 2.25, w: 4.8, h: 0.52, fontFace: FONT, fontSize: 13, bold: true, color: C.white, valign: 'middle', margin: 0 });
  s.addText('Стандартные условия', { x: X[1], y: 2.25, w: 2.4, h: 0.52, fontFace: FONT, fontSize: 12, bold: true, color: C.white, valign: 'middle', margin: 0 });
  s.addText('Проверка на прочность', { x: X[2], y: 2.25, w: 2.8, h: 0.52, fontFace: FONT, fontSize: 12, bold: true, color: 'FF8A98', valign: 'middle', margin: 0 });
  rows.forEach((p, i) => {
    const y = 2.92 + i * 0.66;
    if (i % 2 === 0) s.addShape(pptx.ShapeType.rect, { x: 0.45, y, w: TW, h: 0.62, fill: { color: C.white, transparency: 94 }, line: { color: C.white, transparency: 100 } });
    s.addText(p.label, { x: X[0] + 0.25, y, w: 5.0, h: 0.62, fontFace: FONT, fontSize: 14, color: C.text, valign: 'middle', margin: 0 });
    numCell(s, X[1], y + 0.03, 2.4, p.standard, { size: 20 });
    numCell(s, X[2], y + 0.03, 2.8, p.hard, { size: 20 });
  });
  const steps = ['Протокол и хэш данных — до прогона', 'Настройка — только на обучающих данных', 'Один прогон на отложенных', 'Все цифры — из одного файла'];
  steps.forEach((t, i) => {
    const x = 0.45 + i * 3.13;
    card(s, x, 5.05, 2.95, 1.0, { transparency: 88 });
    s.addText(String(i + 1), { x: x + 0.2, y: 5.12, w: 0.4, h: 0.85, fontFace: FONT, fontSize: 22, bold: true, color: C.red, valign: 'middle', margin: 0 });
    s.addText(t, { x: x + 0.65, y: 5.12, w: 2.2, h: 0.85, fontFace: FONT, fontSize: 12, bold: true, color: C.white, valign: 'middle', margin: 0 });
  });
  note(s, 'Почему справа строже: грейд — по шести ступеням; в тесте кандидаты угадывают, чаще завышают заявку, больше людей у порогов; в подборе часть анкет завышает грейд и стек. Обе колонки — один прогон на отложенных данных. Кандидаты модельные, не люди; условия, N и команда пересчёта — на сайте, раздел «Как мы проверяем себя».', { y: 6.18, h: 0.62, size: 9 });
}


// ---------- В7. ФСП и команда ----------
{
  const s = base('ФСП и команда');
  title(s, 'Для Федерации — канал к работодателям.\nКоманда Neuropeople', { size: 28 });
  card(s, 0.45, 2.25, 5.5, 3.95);
  s.addText('Официальные протоколы ФСП', { x: 0.7, y: 2.4, w: 5.0, h: 0.4, fontFace: FONT, fontSize: 14, bold: true, color: C.ok, margin: 0 });
  const fd = realv('fsp'), fr = realv('fsp_results');
  numCell(s, 0.7, 2.85, 2.4, fd.value, { size: 30 });
  s.addText('протоколов в индексе', { x: 0.7, y: 3.4, w: 2.4, h: 0.35, fontFace: FONT, fontSize: 10.5, color: C.muted, margin: 0 });
  numCell(s, 3.2, 2.85, 2.6, fr.value, { size: 30 });
  s.addText('результатов спортсменов', { x: 3.2, y: 3.4, w: 2.6, h: 0.35, fontFace: FONT, fontSize: 10.5, color: C.muted, margin: 0 });
  s.addText(bullets(['достижение в карточке — со ссылкой на строку протокола', 'спортивный разряд — понятным работодателю языком', 'кабинет ФСП: спрос компаний по регионам и направлениям']),
    { x: 0.7, y: 3.95, w: 5.05, h: 2.1, fontFace: FONT, fontSize: 12.5, color: C.text, margin: 0, valign: 'top' });
  s.addImage({ path: A('team_photo.jpg'), x: 6.2, y: 2.25, w: 6.65, h: 6.65 * 1000 / 2170 });
  const ty = 2.25 + 6.65 * 1000 / 2170 + 0.12;
  s.addText([{ text: 'Дмитрий Кузнецов', options: { bold: true, color: C.white } }, { text: '\nинженер по качеству и внедрению', options: { color: C.muted, fontSize: 10.5 } }],
    { x: 6.2, y: ty, w: 3.3, h: 0.7, fontFace: FONT, fontSize: 13, margin: 0, align: 'center', valign: 'top' });
  s.addText([{ text: 'Денис Михеев', options: { bold: true, color: C.white } }, { text: '\nкапитан, «Neuropeople»', options: { color: C.muted, fontSize: 10.5 } }],
    { x: 9.55, y: ty, w: 3.3, h: 0.7, fontFace: FONT, fontSize: 13, margin: 0, align: 'center', valign: 'top' });
  s.addText([{ text: 'Проверьте сами: ', options: { color: C.muted } }, { text: `${SITE}/demo`, options: { bold: true, color: C.white, hyperlink: { url: `https://${SITE}/demo` } } }],
    { x: 6.2, y: 6.05, w: 6.65, h: 0.4, fontFace: FONT, fontSize: 14, margin: 0, align: 'center' });
}

// ===================== ПРИЛОЖЕНИЕ: для вопросов жюри =====================

// ---------- Приложение: разделитель ----------
{
  const s = pptx.addSlide();
  N += 1;
  s.background = { path: A('bg_title.jpg') };
  s.addImage({ path: A('logo_draft.png'), x: 0.75, y: 2.4, w: 3.0, h: 0.957 });
  s.addText('Приложение', { x: 0.45, y: 3.6, w: 9.6, h: 0.8, fontFace: FONT, fontSize: 36, bold: true, color: C.white, margin: 0 });
  s.addText('Подробности для вопросов жюри: замечания экспертизы, как мы проверяем, механика подбора, тест, валидация, документы ФСП, интеграции, архитектура, монетизация, ссылки.',
    { x: 0.45, y: 4.45, w: 8.6, h: 0.9, fontFace: FONT, fontSize: 15, color: C.text, margin: 0, valign: 'top' });
}


// ---------- П1. Вы сказали — мы сделали: 12 замечаний экспертизы 20.10 ----------
{
  const s = base('Замечания экспертизы');
  title(s, 'Вы сказали — мы сделали:\n12 замечаний экспертизы 20.10', { size: 28 });
  const items = [
    ['Место — по тесту и ФСП, стек — фильтр', 'Порядок задают тест по навыкам вакансии и ФСП; заявленное без теста не влияет', '/employer/needs/<id>'],
    ['Фильтр грейда без заявленного уровня', 'Фильтр отбирает только грейд, подтверждённый тестом', '/employer/search'],
    ['Ответ не должен уходить в браузер', 'Ключи хранятся и проверяются только на сервере; сквозной тест', 'e2e 21-no-answer-keys'],
    ['Демо-код ФСП ID — не как рабочий', 'Код виден только в демо-роли, с пометкой «Демо-стенд»', '/candidate/fsp'],
    ['Порядок — с потребностью и без', 'Два правила описаны и покрыты тестами', 'docs/matching/ORDER.md'],
    ['«Почему» — без устного перевода', 'Пояснения полными фразами, без внутренних кодов', 'карточка в подборке'],
    ['Вилка до согласия, контакты закрыты', 'Без вилки — ошибка 422; отзыв согласия снова закрывает контакты', '/candidate/invitations'],
    ['Провал не снимает грейд; без ФСП — в выдаче', 'Правило в коде и тестах; ФСП без истории — ноль, без штрафа', '/demo'],
    ['Секреты — не в репозитории', 'Только .env на сервере; проверка всей истории gitleaks', '.gitleaks.toml'],
    ['Письмо подтверждения — настоящее', 'Код приходит письмом; почта — с проверкой сертификата', '/register'],
    ['README без обещаний', 'Каждая цифра — из NUMBERS.json с условием; сборка проверяет ссылки', 'README.md'],
    ['Что изменилось к финалу и почему', 'Отдельный документ по волнам доработки', 'docs/submission/CHANGELOG.md'],
  ];
  const cw = 3.0, ch = 1.32, gx = 0.133, gy = 0.1, x0 = 0.45, y0 = 2.05;
  items.forEach(([said, did, where], i) => {
    const x = x0 + (i % 4) * (cw + gx), y = y0 + Math.floor(i / 4) * (ch + gy);
    card(s, x, y, cw, ch, { transparency: 88 });
    s.addText(String(i + 1), { x: x + 0.14, y: y + 0.1, w: 0.38, h: 0.32, fontFace: FONT, fontSize: 14, bold: true, color: C.red, margin: 0, valign: 'top' });
    s.addText(said, { x: x + 0.5, y: y + 0.1, w: cw - 0.62, h: 0.42, fontFace: FONT, fontSize: 10, bold: true, color: C.white, margin: 0, valign: 'top' });
    s.addText(did, { x: x + 0.14, y: y + 0.55, w: cw - 0.26, h: 0.48, fontFace: FONT, fontSize: 9, color: C.text, margin: 0, valign: 'top' });
    s.addText(where, { x: x + 0.14, y: y + 1.02, w: cw - 0.26, h: 0.25, fontFace: FONT, fontSize: 8.5, bold: true, color: C.lav, margin: 0, valign: 'top' });
  });
  note(s, 'Каждую строку можно проверить самостоятельно — адрес на сайте, тест или файл указан в карточке. Полная таблица с методами API и тестами — README, раздел «Замечания экспертизы 20.10 — как проверить».', { y: 6.42 });
}

// ---------- П2. Как мы проверяем: процедура и журнал отчётных прогонов ----------
{
  const s = base('Как мы проверяем');
  title(s, 'Как мы проверяем себя:\nсначала правила и хэш, потом один прогон', { size: 28 });
  const steps = [
    ['Протокол и хэш — до прогона', 'что меряем и на каких данных — коммит в git; отложенный набор заморожен, его хэш записан'],
    ['Один прогон на отложенных', 'настройка — только на обучающих данных; повторного отчётного прогона на тех же данных нет, лучший из нескольких не выбираем'],
    ['Независимый пересчёт', 'независимый рецензент повторяет прогон в чистой копии репозитория и сверяет каждое поле'],
    ['Две колонки', 'каждая метрика — в стандартных условиях и в проверке на прочность, рядом'],
    ['Один файл цифр', 'docs/NUMBERS.json → сайт, README, документация и эти слайды; цифры руками не пишем'],
  ];
  steps.forEach(([h, b], i) => {
    const y = 2.05 + i * 0.84;
    card(s, 0.45, y, 5.2, 0.76, { transparency: 88 });
    s.addText(String(i + 1), { x: 0.6, y, w: 0.4, h: 0.76, fontFace: FONT, fontSize: 20, bold: true, color: C.red, valign: 'middle', margin: 0 });
    s.addText(h, { x: 1.05, y: y + 0.07, w: 4.5, h: 0.3, fontFace: FONT, fontSize: 11.5, bold: true, color: C.white, margin: 0, valign: 'top' });
    s.addText(b, { x: 1.05, y: y + 0.36, w: 4.5, h: 0.4, fontFace: FONT, fontSize: 8.8, color: C.text, margin: 0, valign: 'top' });
  });
  const J = FACTS.journal || [];
  const jx = 5.9, jw = 6.95;
  card(s, jx, 2.05, jw, 4.12);
  s.addText('Журнал отчётных прогонов', { x: jx + 0.22, y: 2.15, w: jw - 0.4, h: 0.38, fontFace: FONT, fontSize: 13, bold: true, color: C.ok, margin: 0 });
  s.addText('Что заморожено до прогона', { x: jx + 4.0, y: 2.18, w: 2.8, h: 0.34, fontFace: FONT, fontSize: 9, color: C.muted, margin: 0, valign: 'middle' });
  J.slice(0, 7).forEach((j, i) => {
    const y = 2.6 + i * 0.5;
    if (i % 2 === 0) s.addShape(pptx.ShapeType.rect, { x: jx + 0.1, y, w: jw - 0.2, h: 0.48, fill: { color: C.white, transparency: 94 }, line: { color: C.white, transparency: 100 } });
    s.addText([{ text: j.what, options: { color: C.white, bold: true } }, ...(j.extra ? [{ text: '\n' + j.extra, options: { color: C.muted, fontSize: 8.5 } }] : [])],
      { x: jx + 0.22, y, w: 3.75, h: 0.48, fontFace: FONT, fontSize: 9.5, margin: 0, valign: 'middle' });
    s.addText([{ text: j.kind + ' ', options: { color: C.muted } }, { text: j.hash, options: { color: C.white, bold: true, fontFace: 'Courier New' } }],
      { x: jx + 4.0, y, w: 2.85, h: 0.48, fontFace: FONT, fontSize: 9.5, margin: 0, valign: 'middle' });
  });
  note(s, 'Хэш — начало SHA-256 из docs/NUMBERS.json. Где кандидаты модельные, а не люди, — это написано рядом с каждой цифрой.', { y: 6.3 });
}

// (прежний слайд «Проблема» — в выступлении, слайд 2)

// ---------- 3. Решение ----------
{
  const s = base('Решение');
  title(s, 'Наоборот: компания сама приходит\nк кандидату, чей уровень доказан');
  const rows = [
    ['КАНДИДАТ', [['Регистрация и опрос', 'почта с подтверждением, направление, стек, желаемый грейд'], ['Тест вместо резюме', 'адаптивный: следующее задание зависит от ответов'], ['Категория «направление · грейд»', 'только по тесту; достижения ФСП — по протоколам']]],
    ['РАБОТОДАТЕЛЬ', [['Потребность своими словами', 'текст или файл вакансии; требования — с цитатой'], ['Подборка с объяснением', 'обезличенные карточки: почему кандидат здесь'], ['Приглашение с вилкой', 'зарплата «от–до» обязательна; контакты — после согласия']]],
  ];
  rows.forEach(([who, steps], r) => {
    const y = 2.35 + r * 1.85;
    s.addText(who, { x: 0.45, y: y + 0.45, w: 1.9, h: 0.5, fontFace: FONT, fontSize: 12, bold: true, color: r ? C.lav : C.red, margin: 0 });
    steps.forEach(([h, b], i) => {
      const x = 2.35 + i * 3.55;
      card(s, x, y, 3.3, 1.55);
      s.addShape(pptx.ShapeType.ellipse, { x: x + 0.2, y: y + 0.2, w: 0.44, h: 0.44, fill: { color: r ? C.indigo : C.red }, line: { color: C.white, transparency: 60 } });
      s.addText(String(r * 3 + i + 1), { x: x + 0.2, y: y + 0.2, w: 0.44, h: 0.44, fontFace: FONT, fontSize: 13, bold: true, color: C.white, align: 'center', valign: 'middle', margin: 0 });
      s.addText(h, { x: x + 0.78, y: y + 0.14, w: 2.4, h: 0.58, fontFace: FONT, fontSize: 13, bold: true, color: C.white, valign: 'middle', margin: 0 });
      s.addText(b, { x: x + 0.2, y: y + 0.78, w: 2.95, h: 0.7, fontFace: FONT, fontSize: 11, color: C.text, valign: 'top', margin: 0 });
      if (i < 2) s.addShape(pptx.ShapeType.line, { x: x + 3.3, y: y + 0.78, w: 0.25, h: 0, line: { color: C.lav, width: 1.5, endArrowType: 'triangle' } });
    });
  });
  note(s, 'Кандидат без истории ФСП ничего не теряет: составляющая ФСП в подборке у него просто равна нулю, без штрафа.', { y: 6.15 });
}

// ---------- 4. Механика подбора ----------
{
  const s = base('Механика подбора');
  title(s, 'Подборка из подтверждённых фактов —\nи объяснение у каждого кандидата');
  // состав скора (доли из кода ranking.py)
  card(s, 0.45, 2.3, 5.6, 3.95);
  s.addText('Из чего складывается место в подборке', { x: 0.7, y: 2.45, w: 5.2, h: 0.45, fontFace: FONT, fontSize: 14, bold: true, color: C.white, margin: 0 });
  const parts = [['Результат теста по грейду и навыкам', 'w_test', C.indigo], ['Обязательный стек', 'w_stack_required', C.lav], ['Желательный стек', 'w_stack_desired', '7C74E8'], ['Подтверждённые достижения ФСП', 'w_fsp', C.red], ['Короткое задание работодателя', 'w_probe', C.ok]];
  parts.forEach(([lab, k, col], i) => {
    const y = 3.05 + i * 0.6;
    const v = R[k];
    s.addText(lab, { x: 0.7, y, w: 3.0, h: 0.45, fontFace: FONT, fontSize: 11.5, color: C.text, valign: 'middle', margin: 0 });
    s.addShape(pptx.ShapeType.roundRect, { x: 3.75, y: y + 0.1, w: Math.max(0.08, (v / 50) * 1.6), h: 0.26, fill: { color: col }, line: { color: col }, rectRadius: 0.05 });
    s.addText(`${v} %`, { x: 5.35, y, w: 0.6, h: 0.45, fontFace: FONT, fontSize: 12, bold: true, color: C.white, align: 'right', valign: 'middle', margin: 0 });
  });
  s.addText('Доли — из кода ранжирования (backend/app/modules/matching/ranking.py).', { x: 0.7, y: 5.75, w: 5.2, h: 0.4, fontFace: FONT, fontSize: 9.5, color: C.faint, margin: 0 });
  const rules = [
    ['Грейд — только подтверждённый', 'Фильтр категории работает по тесту, не по резюме. Без подтверждения кандидат виден по направлению, последним и с пометкой.'],
    ['ФСП — бонус, а не штраф', '«Подтверждено ФСП» — полный вес, «ждёт подтверждения» — половина, заявлено без документа — ноль.'],
    ['Уточнение без потери', 'Каждый фильтр создаёт новую версию подборки; прежние сохраняются и сравниваются.'],
  ];
  rules.forEach(([h, b], i) => cardText(s, 6.3, 2.3 + i * 1.34, 6.55, 1.22, h, b, { headSize: 13.5, bodySize: 11 }));
}

// ---------- 5. Тестирование ----------
{
  const s = base('Тестирование');
  title(s, 'Свой вариант у каждого —\nсложность сопоставима');
  bigNum(s, 0.45, 2.15, 2.9, fv('bank_families'), 'семейств заданий в банке: генераторы, а не готовые вопросы');
  bigNum(s, 3.45, 2.15, 2.9, fv('bank_variants'), 'уникальных вариантов на проверке банка');
  bigNum(s, 6.45, 2.15, 2.9, fv('bank_checks_failed'), 'ошибок в ключах: каждый вариант с кодом проверяется исполнением эталонного решения');
  const items = [
    ['Адаптивный тест', 'Следующее задание подбирается по ответам; около трети — практика: код и развёрнутый ответ.'],
    ['Три исхода вердикта', 'Грейд подтверждён · не подтверждён · у самой границы — короткий второй этап вместо угадывания.'],
    ['Утечка почти не помогает', 'Варианты по зерну, контроль частоты показа, повтор — на новых семействах, ключи только на сервере.'],
    ['Честность без автобана', 'Два и больше сигнала (вкладки, вставка, время) — дополнительная проверка: задания у порога или устная защита.'],
  ];
  items.forEach(([h, b], i) => cardText(s, 0.45 + i * 3.13, 3.75, 2.95, 2.45, h, b, { headSize: 12, bodySize: 11, accent: [C.red, C.lav, C.ok, C.indigo][i] }));
  note(s, `${F.bank_families ? F.bank_families.cond[0].toUpperCase() + F.bank_families.cond.slice(1) + '.' : ''} Повтор на тот же грейд — через ${R.retake_same_grade_days} дней, смена подтверждённого грейда — раз в ${R.grade_change_interval_days} дней.`, { y: 6.32 });
  s.addImage({ path: A('deco_medal.png'), x: 10.0, y: 1.0, w: 2.6, h: 2.6 });
}

// ---------- 6. Валидация: процедура ----------
{
  const s = base('Тестирование и валидация');
  title(s, 'Процедура, которой можно не верить\nна слово — её можно повторить');
  const steps = [['Протокол', 'что и как меряем — коммит до прогона'], ['Заморозка', 'отложенный набор, хэш в git'], ['Настройка', 'только на обучающих данных'], ['Один прогон', 'на отложенных данных, без выбора лучшего'], ['Один файл цифр', 'NUMBERS.json → сайт, документы, слайды']];
  steps.forEach(([h, b], i) => {
    const x = 0.45 + i * 2.5;
    card(s, x, 2.35, 2.3, 1.6);
    s.addText(String(i + 1), { x: x + 0.2, y: 2.47, w: 0.5, h: 0.45, fontFace: FONT, fontSize: 20, bold: true, color: C.red, margin: 0 });
    s.addText(h, { x: x + 0.2, y: 2.92, w: 1.95, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.white, margin: 0 });
    s.addText(b, { x: x + 0.2, y: 3.32, w: 1.95, h: 0.6, fontFace: FONT, fontSize: 10.5, color: C.text, margin: 0, valign: 'top' });
    if (i < 4) s.addShape(pptx.ShapeType.line, { x: x + 2.3, y: 3.15, w: 0.2, h: 0, line: { color: C.lav, width: 1.5, endArrowType: 'triangle' } });
  });
  const what = [
    ['Тест', 'Модельные кандидаты с известным уровнем проходят тот же движок, что на сайте; три «мира»: точные параметры, неточная трудность заданий, ошибки проверки.'],
    ['Подбор', 'Отложенные синтетические миры с известной релевантностью; сравнение с поиском по тексту резюме и с подбором без теста.'],
    ['Реальные данные', 'Вакансии hh.ru — разбор потребности; официальные протоколы ФСП — сверка достижений; защита проверки — отложенный набор атак.'],
  ];
  what.forEach(([h, b], i) => cardText(s, 0.45 + i * 4.17, 4.2, 3.98, 1.95, h, b, { headSize: 13.5, bodySize: 11 }));
  note(s, 'Где кандидаты модельные — это написано рядом с цифрой. Пересчёт любой цифры — одной командой, указанной в docs/NUMBERS.json.', { y: 6.32 });
}

// ---------- 7. Документы ФСП ----------
{
  const s = base('Документы ФСП');
  title(s, 'Достижение — со ссылкой\nна официальный протокол');
  bigNum(s, 0.45, 2.1, 2.6, fv('fsp_documents'), 'официальных протоколов ФСП России в индексе');
  bigNum(s, 3.15, 2.1, 2.6, fv('fsp_results'), 'результатов спортсменов');
  bigNum(s, 5.85, 2.1, 2.6, fv('fsp_regions'), 'субъектов РФ');
  const st = [['Подтверждено ФСП', 'вход через ФСП ID или решение федерации', 'полный вес', C.ok], ['Ждёт подтверждения', 'кандидат нашёл свою строку в протоколе', 'половина', C.lav], ['Заявлено', 'без документа', 'ноль', C.faint], ['Истории ФСП нет', 'ничего не указано', 'ноль, без штрафа', C.muted]];
  card(s, 0.45, 3.65, 7.9, 2.55);
  s.addText('Статус достижения в карточке кандидата', { x: 0.7, y: 3.77, w: 7.4, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.white, margin: 0 });
  st.forEach(([a, b, c, col], i) => {
    const y = 4.25 + i * 0.47;
    s.addShape(pptx.ShapeType.ellipse, { x: 0.72, y: y + 0.12, w: 0.18, h: 0.18, fill: { color: col }, line: { color: col } });
    s.addText(a, { x: 1.0, y, w: 2.5, h: 0.42, fontFace: FONT, fontSize: 11.5, bold: true, color: C.white, valign: 'middle', margin: 0 });
    s.addText(b, { x: 3.5, y, w: 3.0, h: 0.42, fontFace: FONT, fontSize: 10.5, color: C.text, valign: 'middle', margin: 0 });
    s.addText(c, { x: 6.5, y, w: 1.7, h: 0.42, fontFace: FONT, fontSize: 10.5, bold: true, color: col === C.faint || col === C.muted ? C.muted : col, valign: 'middle', margin: 0, align: 'right' });
  });
  cardText(s, 8.6, 2.1, 4.25, 2.0, 'Разряд по ЕВСК', 'Выводится из места, числа участвующих субъектов РФ и состава судейской коллегии — и показывается с основанием.', { headSize: 13.5, bodySize: 11 });
  cardText(s, 8.6, 4.25, 4.25, 1.95, 'Персональные данные', 'Из протокола — только ФИО, год рождения, регион, место, разряд. Индекс вне репозитория, ключи поиска — HMAC, открытого каталога спортсменов нет.', { headSize: 13.5, bodySize: 11 });
  note(s, F.fsp_documents ? `${F.fsp_documents.cond[0].toUpperCase()}${F.fsp_documents.cond.slice(1)}.` : 'Индекс протоколов пересчитывается.', { y: 6.32 });
}

// ---------- 8. Интеграции ----------
{
  const s = base('Интеграции');
  title(s, 'Встраивается в то, чем уже\nпользуются федерация и компании');
  const t = [
    ['ФСП ID', 'вход и связь профиля по OIDC; демо-стенд на Keycloak, переключение на боевой — настройкой'],
    ['Реестр ФСП', 'контракт API реестра и рабочий адаптер; до появления API — официальные протоколы'],
    ['hh.ru', 'данные рынка: спрос по навыкам и зарплатные вилки по категориям'],
    ['ATS работодателя', 'передача кандидата и этапы найма в обе стороны, универсальный вебхук'],
    ['ЕГРЮЛ', 'проверка компании и индекс доверия — защита от фиктивных вакансий'],
    ['Файлы', 'профиль из PDF-резюме, потребность из файла вакансии, стандартизированный PDF-профиль'],
    ['Уведомления', 'письма, уведомления в кабинете и в браузере, подписка на новых кандидатов'],
    ['Мобильное', 'адаптивный сайт, установка как приложение, Android-приложение'],
  ];
  t.forEach(([h, b], i) => {
    const col = i % 4, row = Math.floor(i / 4);
    cardText(s, 0.45 + col * 3.13, 2.3 + row * 2.0, 2.95, 1.82, h, b, { headSize: 14, bodySize: 10.5 });
  });
  note(s, `Открытое API: ${R.api_operations} операций в спецификации OpenAPI — ${SITE}/api/docs.`, { y: 6.32 });
}

// ---------- 9. Честные цифры: две колонки ----------
{
  const s = base('Честные цифры');
  title(s, 'Одни и те же метрики — в стандартных\nусловиях и в проверке на прочность', { size: 26 });
  const colX = [0.45, 4.6, 6.75], colW = [4.1, 2.1, 2.1];
  const TW = 8.85;
  card(s, 0.45, 2.05, TW, 0.62, { transparency: 85 });
  s.addText('Метрика', { x: colX[0] + 0.2, y: 2.1, w: colW[0], h: 0.52, fontFace: FONT, fontSize: 11.5, bold: true, color: C.white, valign: 'middle', margin: 0 });
  s.addText('Стандартные условия\n(как в аналогичных решениях)', { x: colX[1], y: 2.08, w: colW[1], h: 0.56, fontFace: FONT, fontSize: 9.5, bold: true, color: C.white, valign: 'middle', margin: 0 });
  s.addText('Проверка на прочность\n(наши жёсткие условия)', { x: colX[2], y: 2.08, w: colW[2] + 0.3, h: 0.56, fontFace: FONT, fontSize: 9.5, bold: true, color: 'FF8A98', valign: 'middle', margin: 0 });
  const rows = PAIRS.pairs.slice(0, 11);
  const rh = 0.31;
  rows.forEach((p, i) => {
    const y = 2.75 + i * rh;
    if (i % 2 === 0) s.addShape(pptx.ShapeType.rect, { x: 0.45, y, w: TW, h: rh, fill: { color: C.white, transparency: 94 }, line: { color: C.white, transparency: 100 } });
    s.addText(p.label, { x: colX[0] + 0.2, y, w: colW[0] - 0.25, h: rh, fontFace: FONT, fontSize: 9.5, color: C.text, valign: 'middle', margin: 0 });
    for (const [k, x, w] of [['standard', colX[1], colW[1]], ['hard', colX[2], colW[2]]]) {
      const v = p[k];
      s.addText(v ? v.text : PENDING, { x, y, w, h: rh, fontFace: FONT, fontSize: v ? 12.5 : 9.5, bold: !!v, color: v ? C.white : C.faint, valign: 'middle', margin: 0 });
    }
  });
  // реальные данные — справа
  card(s, 9.5, 2.05, 3.35, 4.11);
  s.addText('Реальные данные', { x: 9.72, y: 2.17, w: 3.0, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.ok, margin: 0 });
  const real = PAIRS.real.filter((r) => r.value).slice(0, 4);
  real.forEach((r, i) => {
    const y = 2.6 + i * 0.86;
    s.addText(r.value.text, { x: 9.72, y, w: 3.0, h: 0.42, fontFace: FONT, fontSize: 18, bold: true, color: C.white, margin: 0, valign: 'bottom' });
    s.addText(r.label, { x: 9.72, y: y + 0.43, w: 3.0, h: 0.42, fontFace: FONT, fontSize: 9.5, color: C.muted, margin: 0, valign: 'top' });
  });
  const c1 = (PAIRS.pairs.find((p) => p.standard && p.standard.cond) || {}).standard;
  const c2 = (PAIRS.pairs.find((p) => p.hard && p.hard.cond) || {}).hard;
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const condLine = [c1 ? `${cap(c1.cond)}.` : '', c2 ? `${cap(c2.cond)}.` : ''].filter(Boolean).join('  ');
  note(s, (condLine ? condLine + ' ' : '') + 'Модельные кандидаты, не люди; какие условия идут заголовком, решено до прогонов. Все условия, N и команды пересчёта — docs/NUMBERS.json, приложение Б документации, /validation.', { y: 6.22, h: 0.72, size: 7.5 });
}

// ---------- 10. Архитектура ----------
{
  const s = base('Архитектура');
  title(s, 'Модульный монолит: просто развернуть,\nлегко проверить');
  card(s, 0.45, 2.15, 7.6, 4.1, { fill: 'FFFFFF', transparency: 0, lineT: 100 });
  s.addImage({ path: path.join(ROOT, 'docs/submission/assets/diagram_2.png'), x: 0.6, y: 2.27, w: 7.3, h: 7.3 * 1708 / 2678, sizing: { type: 'contain', w: 7.3, h: 3.86 } });
  const st = [
    ['Интерфейс', 'React, TypeScript, Vite, Tailwind; адаптив 360 / 768 / 1280'],
    ['API', 'Python, FastAPI, SQLAlchemy, Alembic; модули со слоями'],
    ['Данные', 'PostgreSQL 16; банк заданий — отдельный пакет без сети'],
    ['Запуск', 'Docker Compose, одна команда make up; миграции и демо-данные сами'],
    ['Без внешних ключей', 'нет модели — правила и ручная проверка; нет почты — коды в лог'],
  ];
  st.forEach(([h, b], i) => {
    const y = 2.15 + i * 0.83;
    card(s, 8.3, y, 4.55, 0.73);
    s.addText(h, { x: 8.5, y: y + 0.05, w: 4.2, h: 0.3, fontFace: FONT, fontSize: 12, bold: true, color: C.white, margin: 0 });
    s.addText(b, { x: 8.5, y: y + 0.34, w: 4.2, h: 0.36, fontFace: FONT, fontSize: 9.5, color: C.text, margin: 0, valign: 'top' });
  });
}

// ---------- 11. Монетизация ----------
{
  const s = base('Монетизация');
  title(s, 'Кандидатам — бесплатно.\nПлатят за подтверждённый найм');
  const t = [
    ['Старт', 'бесплатно', ['ограниченное число приглашений', 'подборка с объяснением', 'проверка компании']],
    ['Найм', 'для регулярного подбора', ['интеграция с ATS', 'задания с автопроверкой', 'аналитика зарплатных вилок']],
    ['Партнёр ФСП', 'в спонсорском пакете', ['метка «Партнёр ФСП» в карточке компании', 'отборочные задачи компании в соревнованиях', 'кубки работодателя под брендом компании']],
  ];
  t.forEach(([h, sub1, items], i) => {
    const x = 0.45 + i * 4.17;
    card(s, x, 2.3, 3.98, 2.6);
    s.addText(h, { x: x + 0.25, y: 2.45, w: 3.5, h: 0.45, fontFace: FONT, fontSize: 17, bold: true, color: C.white, margin: 0 });
    s.addText(sub1, { x: x + 0.25, y: 2.9, w: 3.5, h: 0.35, fontFace: FONT, fontSize: 11, color: [C.ok, C.lav, 'FF8A98'][i], margin: 0 });
    s.addText(bullets(items), { x: x + 0.25, y: 3.35, w: 3.55, h: 1.6, fontFace: FONT, fontSize: 11, color: C.text, margin: 0, valign: 'top' });
  });
  cardText(s, 0.45, 5.05, 12.4, 1.25, 'Спонсорские пакеты федерации', 'Партнёр соревнования · партнёр направления · генеральный партнёр: соревнования ФСП становятся источником найма, а спортсмены получают карьерное преимущество от своих результатов. Оформление — заявкой на странице тарифов.', { headSize: 13, bodySize: 10.5 });
}

// ---------- 12. Команда и ссылки ----------
{
  const s = base('Команда');
  title(s, 'Команда Neuropeople');
  sub(s, 'Оператор платформы — команда Neuropeople. Решение подготовлено для специального трека ФСП «Лидеры цифровой трансформации 2026».', { y: 1.65, w: 7.8, h: 0.8, size: 14 });
  const links = [
    ['Рабочий сайт', `https://${SITE}`],
    ['Демо для жюри: вход в любую роль в один клик', `https://${SITE}/demo`],
    ['Методика и все цифры с условиями', `https://${SITE}/validation`],
    ['Описание API', `https://${SITE}/api/docs`],
    ['Исходный код', 'https://github.com/neuropeopleteam-afk/draft'],
  ];
  card(s, 0.45, 2.7, 7.8, 3.5);
  links.forEach(([h, u], i) => {
    const y = 2.88 + i * 0.64;
    s.addText(h, { x: 0.7, y, w: 7.3, h: 0.28, fontFace: FONT, fontSize: 11, color: C.muted, margin: 0 });
    s.addText(u.replace('https://', ''), { x: 0.7, y: y + 0.27, w: 7.3, h: 0.32, fontFace: FONT, fontSize: 14, bold: true, color: C.white, margin: 0, hyperlink: { url: u } });
  });
  s.addImage({ path: A('logo_draft.png'), x: 8.95, y: 2.7, w: 2.9, h: 0.924 });
  s.addText('Компании выбирают\nподтверждённых', { x: 8.95, y: 3.75, w: 3.9, h: 0.8, fontFace: FONT, fontSize: 16, bold: true, color: C.white, margin: 0 });
  // План, а не результат: калибровки на людях ещё не было
  cardText(s, 8.75, 4.7, 4.1, 1.5, 'Что дальше', 'Калибровка на ответах людей — в плане, не проведена: 300–500 участников, 6–8 недель. Протокол — до начала.', { headSize: 13, bodySize: 11 });
}

// ---------- запись ----------
const out = path.join(HERE, 'Draft_presentation.pptx');
await pptx.writeFile({ fileName: out });
// pptxgenjs пишет <a:pPr> перед каждым фрагментом абзаца; по схеме OOXML он один и первый — оставляем только первый
// (иначе маркеры списка у абзацев из нескольких фрагментов теряются, а PowerPoint может предлагать «восстановить» файл).
{
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(fs.readFileSync(out));
  let fixed = 0;
  for (const name of Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))) {
    const xml = await zip.file(name).async('string');
    const nx = xml.replace(/<a:p>([\s\S]*?)<\/a:p>/g, (m, body) => {
      let seen = false;
      const nb = body.replace(/<a:pPr\b[^>]*?(?:\/>|>[\s\S]*?<\/a:pPr>)/g, (pp) => { if (!seen) { seen = true; return pp; } fixed += 1; return ''; });
      return `<a:p>${nb}</a:p>`;
    });
    if (nx !== xml) zip.file(name, nx);
  }
  fs.writeFileSync(out, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
  console.log('  лишних <a:pPr> убрано:', fixed);
}
console.log('  записано docs/presentation/Draft_presentation.pptx, слайдов:', N);
try {
  execFileSync('soffice', ['--headless', '--convert-to', 'pdf', '--outdir', HERE, out], { stdio: 'ignore', timeout: 240000 });
  console.log('  записано docs/presentation/Draft_presentation.pdf');
} catch (e) {
  console.error('  PDF не собран (нужен LibreOffice):', e.message);
  process.exitCode = 1;
}

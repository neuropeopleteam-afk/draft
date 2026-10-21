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
const PENDING = 'пересчитывается';

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
  s.addText(value ?? PENDING, { x, y, w, h: 0.6, fontFace: FONT, fontSize: value ? size : 14, bold: true, color: value ? color : C.faint, valign: 'bottom', margin: 0 });
  s.addText(label, { x, y: y + 0.62, w, h: 0.62, fontFace: FONT, fontSize: 11, color: C.muted, valign: 'top', margin: 0 });
}
function note(s, text, { x = 0.45, y = 6.42, w = 12.4 } = {}) {
  s.addText(text, { x, y, w, h: 0.45, fontFace: FONT, fontSize: 9.5, color: C.faint, valign: 'top', margin: 0 });
}
const bullets = (arr, opt = {}) => arr.map((t) => ({ text: t, options: { bullet: { indent: 14 }, paraSpaceAfter: 5, ...opt } }));

// ---------- 1. Титул ----------
{
  const s = pptx.addSlide();
  N += 1;
  s.background = { path: A('bg_title.jpg') };
  s.addImage({ path: A('logo_fsp.png'), x: 0.45, y: 0.62, w: 4.4, h: 0.556 });
  s.addImage({ path: A('logo_draft.png'), x: 0.75, y: 2.75, w: 3.6, h: 1.148 });
  s.addText('Компании выбирают подтверждённых', { x: 0.45, y: 4.15, w: 9.6, h: 0.65, fontFace: FONT, fontSize: 28, bold: true, color: C.white, margin: 0, fit: 'shrink' });
  s.addText('Платформа найма IT-специалистов: кандидат один раз подтверждает грейд тестом, достижения ФСП — официальными протоколами, а работодатель сам выходит на него с зарплатой в приглашении.',
    { x: 0.45, y: 4.95, w: 7.4, h: 1.0, fontFace: FONT, fontSize: 14, color: C.text, margin: 0, valign: 'top' });
  s.addText([{ text: 'Команда Neuropeople', options: { bold: true } }, { text: '  ·  оператор команда Neuropeople  ·  ' }, { text: SITE, options: { bold: true, hyperlink: { url: `https://${SITE}` } } }],
    { x: 0.45, y: 6.25, w: 9.5, h: 0.45, fontFace: FONT, fontSize: 13, color: C.white, margin: 0 });
  s.addText('Специальный трек ФСП · Лидеры цифровой трансформации 2026', { x: 0.45, y: 6.7, w: 9.5, h: 0.4, fontFace: FONT, fontSize: 11, color: C.muted, margin: 0 });
}

// ---------- 2. Проблема ----------
{
  const s = base('Проблема');
  title(s, 'Резюме пишут все.\nДоказательств в нём нет');
  sub(s, 'IT-подбор сводится к совпадению ключевых слов. Работодатель читает отклики и верит на слово, кандидат откликается вслепую, а объективные результаты соревнований ФСП до работодателя не доходят.', { y: 2.2, w: 7.6, h: 1.0, size: 14 });
  s.addImage({ path: A('deco_cube.png'), x: 9.75, y: 0.95, w: 2.55, h: 2.55 });
  const y = 3.55, h = 2.2, w = 3.95;
  cardText(s, 0.45, y, w, h, 'Работодатель', 'Сотни откликов разбираются вручную. Навыки в резюме ничем не подтверждены, ошибка найма обходится дорого.', { accent: C.red });
  cardText(s, 0.45 + w + 0.22, y, w, h, 'Кандидат', 'Откликается вслепую: не видит зарплату и условия до разговора, а сильный результат на соревнованиях — просто строка в резюме.', { accent: C.lav });
  cardText(s, 0.45 + 2 * (w + 0.22), y, w, h, 'Федерация ФСП', 'У федерации есть объективные результаты спортсменов, но нет канала к работодателям: соревнования не становятся источником найма.', { accent: C.ok });
}

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
  bigNum(s, 6.45, 2.15, 2.9, fv('bank_checks_failed'), 'ошибок в ключах: каждый вариант проверяется эталонным решением');
  const items = [
    ['Адаптивный тест', 'Следующее задание подбирается по ответам; около трети — практика: код и развёрнутый ответ.'],
    ['Три исхода вердикта', 'Грейд подтверждён · не подтверждён · у самой границы — короткий второй этап вместо угадывания.'],
    ['Утечка не помогает', 'Варианты по зерну, контроль частоты показа, повтор — на новых семействах, ключи только на сервере.'],
    ['Честность без автобана', 'Два и больше сигнала (вкладки, вставка, время) — дополнительная проверка: задания у порога или устная защита.'],
  ];
  items.forEach(([h, b], i) => cardText(s, 0.45 + i * 3.13, 3.75, 2.95, 2.45, h, b, { headSize: 13.5, bodySize: 11, accent: [C.red, C.lav, C.ok, C.indigo][i] }));
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
  cardText(s, 8.6, 4.25, 4.25, 1.95, '152-ФЗ', 'Из протокола — только ФИО, год рождения, регион, место, разряд. Индекс вне репозитория, ключи поиска — HMAC, открытого каталога спортсменов нет.', { headSize: 13.5, bodySize: 11 });
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
  const rows = PAIRS.pairs.slice(0, 10);
  const rh = 0.355;
  rows.forEach((p, i) => {
    const y = 2.75 + i * rh;
    if (i % 2 === 0) s.addShape(pptx.ShapeType.rect, { x: 0.45, y, w: TW, h: rh, fill: { color: C.white, transparency: 94 }, line: { color: C.white, transparency: 100 } });
    s.addText(p.label, { x: colX[0] + 0.2, y, w: colW[0] - 0.25, h: rh, fontFace: FONT, fontSize: 10.5, color: C.text, valign: 'middle', margin: 0 });
    for (const [k, x, w] of [['standard', colX[1], colW[1]], ['hard', colX[2], colW[2]]]) {
      const v = p[k];
      s.addText(v ? v.text : PENDING, { x, y, w, h: rh, fontFace: FONT, fontSize: v ? 12.5 : 9.5, bold: !!v, color: v ? C.white : C.faint, valign: 'middle', margin: 0 });
    }
  });
  // реальные данные — справа
  card(s, 9.5, 2.05, 3.35, 4.25);
  s.addText('Реальные данные', { x: 9.72, y: 2.17, w: 3.0, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.ok, margin: 0 });
  const real = PAIRS.real.filter((r) => r.value).slice(0, 4);
  real.forEach((r, i) => {
    const y = 2.68 + i * 0.9;
    s.addText(r.value.text, { x: 9.72, y, w: 3.0, h: 0.42, fontFace: FONT, fontSize: 18, bold: true, color: C.white, margin: 0, valign: 'bottom' });
    s.addText(r.label, { x: 9.72, y: y + 0.43, w: 3.0, h: 0.42, fontFace: FONT, fontSize: 9.5, color: C.muted, margin: 0, valign: 'top' });
  });
  const c1 = (PAIRS.pairs.find((p) => p.standard && p.standard.cond) || {}).standard;
  const c2 = (PAIRS.pairs.find((p) => p.hard && p.hard.cond) || {}).hard;
  const condLine = [c1 ? `Стандартные: ${c1.cond}.` : '', c2 ? `Прочность: ${c2.cond}.` : ''].filter(Boolean).join('  ');
  note(s, (condLine ? condLine + ' ' : '') + 'Модельные кандидаты, не люди; какие условия идут заголовком, решено до прогонов. Все условия, N и команды пересчёта — docs/NUMBERS.json, приложение Б документации, /validation.', { y: 6.36 });
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
    ['Без внешних ключей', 'нет модели — правила и очередь экспертов; нет почты — коды в лог'],
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
  s.addImage({ path: A('logo_draft.png'), x: 8.95, y: 2.9, w: 3.4, h: 1.084 });
  s.addText('Компании выбирают\nподтверждённых', { x: 8.95, y: 4.3, w: 3.9, h: 1.0, fontFace: FONT, fontSize: 18, bold: true, color: C.white, margin: 0 });
}

// ---------- запись ----------
const out = path.join(HERE, 'Draft_presentation.pptx');
await pptx.writeFile({ fileName: out });
console.log('  записано docs/presentation/Draft_presentation.pptx, слайдов:', N);
try {
  execFileSync('soffice', ['--headless', '--convert-to', 'pdf', '--outdir', HERE, out], { stdio: 'ignore', timeout: 240000 });
  console.log('  записано docs/presentation/Draft_presentation.pdf');
} catch (e) {
  console.error('  PDF не собран (нужен LibreOffice):', e.message);
  process.exitCode = 1;
}

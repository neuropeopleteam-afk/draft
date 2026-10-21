"""Мозг Насти: память разговора, стенограмма, ответ модели по базе знаний и фоновый наставник.

• Сессия разговора (по session_id от браузера): имя, роль, что уже показано, последние реплики, заметки наставника.
• Стенограмма каждой встречи — JSONL в <кэш>/transcripts/<дата>/<время>_<id>.jsonl (контакты маскируются,
  хранится 30 дней): реплики человека и Насти, шаги обзора, решения и время ответа.
• Ответ: сильная модель (по умолчанию Claude Sonnet) с базой знаний (RAG), «страховка» — быстрая модель, если основная
  задумалась. Постоянная часть подсказки помечена для кэша модели — длинная подсказка не замедляет ответ.
• Наставник: после хода человека в фоне ещё более сильная модель читает стенограмму и оставляет Насте подсказку на
  следующий ход (что человеку важно, что показать дальше, говорить ли проще).
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.modules.interview import concierge_rag as rag

log = logging.getLogger("interview.concierge")

MSK = timezone(timedelta(hours=3))
# «провайдер=модель@усилие рассуждений» («@~N» — рассуждение с потолком N токенов). Один мозг — Claude Sonnet 5.5 без
# рассуждений, потоком (замер 21.10 через ретранслятор на полной подсказке: решение 1,8 с, первое предложение 2,0 с,
# стабильно). Gemini 2.5 Flash — страховка: спрашивается, только если решения основной нет за STREAM_HEDGE_S или она
# упала. Наставник в фоне — раз в пять ходов модели.
LLM_MODELS = [m.strip() for m in os.environ.get(
    "CONCIERGE_BRAIN_MODELS",
    "openrouter=anthropic/claude-sonnet-5.5@minimal|openrouter=google/gemini-2.5-flash").split("|") if m.strip()]
# 6,0 с (было 2,5): 21.10 17:33 на претензию первым успел Gemini (2,56 с) и стал оправдываться, Sonnet понял верно на
# 0,3 с позже; прогон 21.10 17:55 — Sonnet бывает 4,6–5,6 с. Отвечает основная, страховка — только если основная молчит 6 с
# или упала (связка «секунду» звучит с 3 с).
STREAM_HEDGE_S = float(os.environ.get("CONCIERGE_STREAM_HEDGE_S", "6.0"))
LLM_PRIMARY_N = int(os.environ.get("CONCIERGE_LLM_PRIMARY_N", "1"))   # сколько первых моделей — основные
LLM_HEDGE_S = float(os.environ.get("CONCIERGE_LLM_HEDGE_S", "3.2"))  # не используется: обе модели — сразу
LLM_DEADLINE_S = float(os.environ.get("CONCIERGE_LLM_DEADLINE_S", "8.0"))
SUPERVISOR_MODEL = os.environ.get("CONCIERGE_SUPERVISOR_MODEL", "openrouter=anthropic/claude-sonnet-5.5@low").strip()
TRANSCRIPT_DAYS = int(os.environ.get("CONCIERGE_TRANSCRIPT_DAYS", "30"))
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="concierge-llm")
_SUP_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="concierge-sup")

STEP_TITLES: dict[str, str] = {
    "home": "главная страница «Драфта»",
    # кандидат — пункты меню по порядку
    "cand-register": "регистрация кандидата: форма, согласия, вход через ФСП ID",
    "emp-register": "регистрация компании: форма, согласия",
    "fsp-register": "вход для Федерации: кабинет по приглашению, ФСП ID",
    "cand-overview": "кабинет кандидата: обзор и дорожная карта",
    "cand-assessment": "опрос и тест на грейд: выбор уровня и режима",
    "cand-category": "категория и грейд: шкала уровня, паспорт грейда с QR, история",
    "cand-defense": "попытки и устная защита: паспорт честности, ИИ-интервьюер",
    "cand-feedback": "карта навыков и рост: что подтянуть, спрос рынка, маршрут роста",
    "cand-profile": "профиль и резюме: контакты, PDF-резюме, карточка «как вас видит работодатель»",
    "cand-invitations": "приглашения кандидату с вилкой и торг",
    "cand-messages": "сообщения кандидата: переписка с работодателями",
    "cand-trio": "связь с ФСП у кандидата: трёхсторонний канал",
    "cand-cups": "кубки работодателей у кандидата: соревнования компаний, таблица результатов",
    "cand-fsp": "паспорт ФСП кандидата: ФСП ID, достижения, индекс достижений",
    "cand-mydata": "мои данные: что хранится, выгрузка, отзыв согласий, удаление",
    "cand-probes": "задания с вилкой у кандидата (меню «Ещё»)",
    "cand-assignments": "задания для вас с автопроверкой (меню «Ещё»)",
    "cand-settings": "настройки и приватность: поля карточки, скрытый минимум зарплаты, согласия (меню «Ещё»)",
    "cand-vacancies": "вакансии для кандидата (меню «Ещё»)",
    "cand-notifications": "уведомления кандидата: каналы и лента (меню «Ещё»)",
    # работодатель
    "emp-home": "кабинет работодателя: обзор и тариф",
    "emp-needs": "потребности и подборки: текст вакансии, разбор требований, подборка",
    "emp-compare": "сравнение кандидатов и ИИ-советник руководителя",
    "emp-squad": "Командный Драфт ФСП: команда под проект и бюджет, пакетный оффер, рентген кода",
    "emp-search": "поиск по базе: фильтры по специализации, грейду, стеку, паспорту ФСП",
    "emp-invitations": "приглашения работодателя: вилки, встречные предложения, передача в ATS",
    "emp-messages": "сообщения работодателя: переписка с кандидатами",
    "emp-trio": "связь с ФСП у работодателя: трёхсторонний канал",
    "emp-ats": "интеграция с ATS «Поток»: журнал передач, этапы найма",
    "emp-cups": "кубки работодателя: соревнование под вакансию, таблица результатов",
    "emp-company": "профиль компании и тариф (меню «Ещё»)",
    "emp-probes": "задания с вилкой для кандидатов (меню «Ещё»)",
    "emp-assignments": "задания с автопроверкой для кандидатов (меню «Ещё»)",
    "emp-vacancies": "вакансии работодателя из «Потока» (меню «Ещё»)",
    "emp-notifications": "уведомления работодателя (меню «Ещё»)",
    "emp-tariffs": "тарифы работодателя: Старт, Найм, Партнёр ФСП (меню «Ещё»)",
    # Федерация
    "fsp-cabinet": "кабинет Федерации: обзор, главное за период, конвертер разряда",
    "fsp-demand": "спрос работодателей: категории и навыки",
    "fsp-effect": "эффект соревнований ФСП: приглашения и зарплаты по дисциплинам и разрядам",
    "fsp-salaries": "зарплаты из офферов против рынка",
    "fsp-funnel": "воронки: соревнование → приглашение → принятие",
    "fsp-cups": "кубки работодателей как мероприятия платформы",
    "fsp-trio": "трёхсторонняя связь у Федерации",
    "fsp-method": "методика и выгрузки: обезличивание, источники, CSV",
    "fsp-security": "безопасность входа: второй фактор",
    "fsp-benefit": "польза для ФСП: регионы, направления, партнёры (по запросу)",
    "fsp-partners": "партнёры ФСП: метка партнёра, заявки (по запросу)",
    # для жюри и общие страницы
    "warroom": "Боевой ИИ-Полигон: архитектура и атаки на оценщика",
    "val-arena": "проверка механики (/validation): числа точности, арена ранжирования и «Красная кнопка» — атаки, которые "
                 "жюри запускает само: раздуть резюме, сменить имя, пол и возраст у всех кандидатов, фальшивый значок ФСП",
    "pricing": "тарифы и монетизация (публичная страница)",
    "install": "приложение на телефон: установка, RuStore",
}

SECTION_TITLES = {"home": "главная", "candidate": "кандидат", "employer": "работодатель", "fsp": "Федерация", "public": "техническое жюри"}
SECTION_ORDER = ("home", "candidate", "employer", "fsp", "public")


def section_of(step: str | None) -> str | None:
    if not step:
        return None
    if step == "home":
        return "home"
    if step.startswith("cand-"):
        return "candidate"
    if step.startswith("emp-"):
        return "employer"
    if step.startswith("fsp-"):
        return "fsp"
    if step in ("warroom", "val-arena", "pricing", "install"):
        return "public"
    return None


def next_section(step: str | None) -> str | None:
    sec = section_of(step)
    if sec not in SECTION_ORDER:
        return None
    k = SECTION_ORDER.index(sec)
    return SECTION_ORDER[k + 1] if k + 1 < len(SECTION_ORDER) else None


# ------------------------------------------------------------------ стенограммы

def _transcripts_dir() -> Path:
    from app.modules.interview.concierge import _CACHE  # тот же каталог кэша голоса (смонтирован на хосте)

    p = _CACHE / "transcripts"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


_PHONE = re.compile(r"(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}|\+\d[\d\s\-()]{9,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TG = re.compile(r"(?:t\.me/|@)[A-Za-z0-9_]{4,}")


def mask(text: str) -> str:
    t = _EMAIL.sub("[почта]", text or "")
    t = _PHONE.sub("[телефон]", t)
    return _TG.sub("[контакт]", t)


def _cleanup_old() -> None:
    try:  # состояния разговоров старше суток
        for f in _sessions_dir().iterdir():
            if f.suffix in (".json", ".lock", ".tmp") and time.time() - f.stat().st_mtime > 86400:
                f.unlink(missing_ok=True)
    except OSError:
        pass
    root = _transcripts_dir()
    cutoff = (datetime.now(MSK) - timedelta(days=TRANSCRIPT_DAYS)).strftime("%Y-%m-%d")
    try:
        for d in root.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


# ------------------------------------------------------------------ сессии
#
# API работает в нескольких процессах: состояние разговора — маленький JSON на общем диске (<кэш>/sessions/<id>.json),
# изменения — под файловой блокировкой (mutate), поэтому ход, событие браузера и наставник из разных процессов
# не затирают друг друга.

@dataclass
class Session:
    sid: str
    started: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)
    name: str | None = None
    role: str | None = None
    shown: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    last_elena: str = ""
    notes: str = ""
    suggest: str | None = None
    tone: str = "normal"
    turns: int = 0
    sup_at: float = 0.0          # когда наставник взялся за разбор (0 — свободен)
    offer: dict | None = None    # что Настя предложила показать последним вопросом («Показать …?»)

    def remember(self, who: str, text: str) -> None:
        if not text:
            return
        self.history.append({"who": who, "text": text[:600]})
        if len(self.history) > 24:
            del self.history[: len(self.history) - 24]
        if who == "elena":
            self.last_elena = text

    @property
    def file(self) -> Path:
        dt = datetime.fromtimestamp(self.started, MSK)
        return _transcripts_dir() / dt.strftime("%Y-%m-%d") / f"{dt.strftime('%H%M%S')}_{self.sid[:12]}.jsonl"


_SID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_FIELDS = ("sid", "started", "touched", "name", "role", "shown", "history", "last_elena", "notes", "suggest", "tone",
           "turns", "sup_at", "offer")


def _sessions_dir() -> Path:
    from app.modules.interview.concierge import _CACHE

    p = _CACHE / "sessions"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _load(sid: str) -> Session | None:
    try:
        d = json.loads((_sessions_dir() / f"{sid}.json").read_text(encoding="utf-8"))
        return Session(**{k: d[k] for k in _FIELDS if k in d})
    except (OSError, ValueError, TypeError):
        return None


def _save(s: Session) -> None:
    fp = _sessions_dir() / f"{s.sid}.json"
    tmp = fp.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({k: getattr(s, k) for k in _FIELDS}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, fp)
    except OSError as e:
        log.warning("concierge session save: %s", e)


def session(sid: str | None) -> Session | None:
    """Снимок состояния разговора (только чтение; изменения — через mutate)."""
    if not sid or not _SID.match(sid):
        return None
    return _load(sid) or Session(sid=sid)


@contextmanager
def mutate(sid: str | None):
    """Изменить состояние разговора под блокировкой; без корректного id — None (ничего не пишется)."""
    if not sid or not _SID.match(sid):
        yield None
        return
    lock_fp = _sessions_dir() / f"{sid}.lock"
    fh = None
    try:
        fh = open(lock_fp, "a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        fh = None
    try:
        s = _load(sid)
        fresh = s is None
        if s is None:
            s = Session(sid=sid)
        yield s
        s.touched = time.time()
        _save(s)
        if fresh and int(s.started) % 20 == 0:
            threading.Thread(target=_cleanup_old, daemon=True).start()
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                fh.close()
            except OSError:
                pass


def write(s: Session | None, who: str, text: str = "", **extra) -> None:
    """Строка стенограммы (дозапись; строки из разных процессов не перемешиваются). Сбой записи разговору не мешает."""
    if s is None:
        return
    try:
        fp = s.file
        fp.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(MSK).strftime("%H:%M:%S.%f")[:-3], "who": who}
        if text:
            rec["text"] = mask(text)[:1200]
        rec.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
        line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(fp, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError as e:
        log.warning("concierge transcript: %s", e)


_WARM_AT = 0.0
_WARM_LOCK = threading.Lock()


def warm_async(min_gap_s: float = 90.0) -> None:
    """Прогрев в этом процессе: соединение с ретранслятором и кэш подсказки у поставщика — первый ход после открытия
    Насти не платит 3–5 с «холодного» запроса (замер 21.10 19:40). Не чаще раза в 90 с на процесс, 1 токен."""
    global _WARM_AT
    if not LLM_MODELS:
        return
    with _WARM_LOCK:
        now = time.time()
        if now - _WARM_AT < min_gap_s:
            return
        _WARM_AT = now

    def run() -> None:
        from app.modules.interview import concierge_stream as cs

        msgs = [{"role": "system", "content": [{"type": "text", "text": _static_prompt(),
                                                "cache_control": {"type": "ephemeral"}}]},
                {"role": "user", "content": "(служебно: проверка связи, ответь одним символом)"}]
        try:
            for _ in cs.stream_llm(msgs, LLM_MODELS[0], max_tokens=1, timeout=10.0):
                break
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=run, daemon=True, name="concierge-warm").start()


def event(sid: str | None, kind: str, *, text: str = "", step: str | None = None, path: str | None = None,
          name: str | None = None, role: str | None = None) -> None:
    """События браузера: open / say (реплика обзора, связка, приветствие) / step / point / mic / close."""
    if kind in ("open", "mic", "step"):
        warm_async()
    with mutate(sid) as s:
        if s is None:
            return
        if name and not s.name:
            from app.modules.interview.concierge import valid_stored_name  # «Сразу» из браузера — не имя
            s.name = valid_stored_name(name[:40]) or ""
        if role:
            s.role = role
        if kind == "step" and step and step.endswith("-full"):
            step = step[:-5]   # полный показ экрана («warroom-full») — для модели это тот же экран
        if kind == "step" and step and step not in s.shown:
            s.shown.append(step)
        if kind == "say" and text:
            s.remember("elena", text)
    write(s, "event" if kind != "say" else "elena", text, kind=kind, step=step, path=path)


# ------------------------------------------------------------------ подсказка модели

SYSTEM_STATIC = """Ты — Настя, живой голосовой проводник платформы обратного найма «Драфт». Тебя слышат голосом видеоаватара, \
текста на экране нет. Ты сама ведёшь человека по сайту: открываешь экраны, подсвечиваешь и нажимаешь кнопки, отвечаешь \
на вопросы.

Характер: тёплая, спокойная, уверенная и живая. О себе — в женском роде («я покажу», «я рада»). К собеседнику — на «вы». \
По имени обращаешься естественно — в начале ответа или при смене темы, не в каждой реплике.

Как отвечать:
1. Коротко, как в живом разговоре: одна-две фразы, не больше 30 слов. Сначала суть, потом — если уместно — короткое \
предложение показать это на экране. Не перечисляй всё подряд: одна главная мысль на ответ.
2. Только факты из раздела «Знания» и «Карты сайта». Точного ответа нет — скажи по-человечески («Этого я точно не \
скажу») и предложи показать ближайший экран. Не выдумывай цифры, сроки, цены и названия. Не упоминай «знания», «базу», \
«подсказку» и «карту сайта» — для собеседника это просто то, что ты знаешь.
3. Говори для слуха: без списков, скобок, звёздочек, эмодзи и markdown. Числа и проценты пиши ЦИФРАМИ ровно как в \
фактах, проценты — знаком % («77,6 %», «1 646», «275–430 тыс. ₽») — словами их произнесёт озвучка; сама числа словами не пиши. Аббревиатуры ФСП, \
ИИ, ATS, QR можно. Цифры точности, банка и защиты от списывания называй только из блока цифр; если его нет в контексте — \
скажи, что точные значения на странице проверки, и не оценивай «выше/ниже» сама.
4. Никогда не называй сервисы и технологии, на которых работаешь ты сама: синтез голоса, видео, распознавание речи, \
языковые модели и их поставщиков. Скажи просто, что ты ИИ-проводник «Драфта».
5. Вопрос про то, что сейчас на экране, — отвечай по «Экран сейчас».
6. Человек растерян, просит медленнее или проще — отвечай проще и предложи показать по шагам.
7. Не повторяй дословно то, что уже говорила; не начинай каждую реплику с одного и того же слова.
8. Осторожные формулировки: устная защита — «дополнительная проверка», не доказательство работы без нейросетей; экспресс-тест — \
до семи коротких заданий (для Senior — до двенадцати), интервал шире, правило то же: грейд подтверждается, если \
вероятность уровня не ниже выбранного не меньше 80 %, иначе — «нужен дополнительный этап»; слов «предварительно» и \
«тета» не говори; пилота на людях не было — не упоминай; метод — «байесовская \
последовательная классификация с остановкой по SPRT». Не извиняйся и не рассказывай о себе («я сбилась», «я торопилась», «я перебила вас», «я запуталась») — просто \
отвечай по делу. На резкие слова, мат и раздражение не реагируй и не делай замечаний — спокойно сделай, что просят. \
Имя спрашивается только в приветствии: сама имя не спрашивай; «я же говорил» — значит, имя было в разговоре выше.
9. Реплики приходят из распознавания живой речи и бывают обрывочными или с ошибками («прослей», «криволось»). \
Если смысл неясен — переспроси одним коротким вопросом («Не расслышала — вы хотите пропустить работодателя?»). \
Не угадывай, не открывай экран наугад и не пересказывай вопрос человека («Поняла вас, вы спрашиваете…») — сразу по делу.
10. Прямо просят показать — показывай сразу (goto или point), без встречного вопроса. Сама предлагаешь — спроси \
(«Показать, как это выглядит?») и обязательно заполни offer — что показать: показ начнётся, когда человек согласится.
11. Ты задала вопрос — реплика человека, скорее всего, ответ на него. Ответ «нет», «не надо» на предложение — не \
показывай, спроси, что интереснее.
12. Сама между кабинетами не прыгай: другой кабинет (кандидат, работодатель, Федерация, жюри) — только если человек \
прямо попросил или согласился. Не возвращайся к разделу, который человек попросил пропустить.
13. Не здоровайся повторно, если уже здоровалась.
14. Тебя перебивают по имени: пока ты говоришь, ты слышишь только обращение «Настя …» — замолкаешь и выполняешь просьбу. \
Если спрашивают, как тебя остановить: сказать «Настя» (или «Настя, стоп»), пробел или кнопка паузы в окне; продолжить — «дальше».
15. Если человек хочет задать вопрос («есть вопрос», «скажи, пожалуйста», «можно спросить») — ответь коротко «Слушаю вас.» \
(action listen) и жди вопрос, не предлагай продолжать обзор. Спрашивают про «предыдущий раздел» — назови его и предложи показать \
(action goto со step этого раздела, если знаешь, какой был).
16. Человек недоволен («почему ты не рассказала», «я просил полностью», «ты не то показала», «зачем ушла») — не \
объясняй и не оправдывайся, а сразу сделай, что он хотел: одна короткая фраза («Поняла, покажу Полигон целиком.») и \
действие — обычно goto на тот экран с "full": true. «Подробнее», «полностью», «целиком» про экран — тоже goto с \
"full": true: ты пройдёшь экран целиком и сама нажмёшь главные кнопки.
17. «Замолчала», «почему молчишь», «что дальше» на экране, который человек сам открыл, — продолжай НА ЭТОМ ЖЕ экране \
(scroll с dir down или короткий рассказ о блоке ниже); в другой раздел или кабинет без просьбы не уводи. Не оправдывайся \
(«я ждала вашего вопроса») — просто продолжи.

Решение — поле action:
• "answer" — ответ на вопрос или реплику; если шёл обзор, после ответа ты сама продолжишь показ с того же места;
• "goto" — показать нужный экран: step — один из шагов ниже; reply — короткая связка («Сейчас покажу.»);
• "point" — показать элемент на текущем экране: point — точный текст элемента из списка «Элементы на экране»; \
ты подсвечиваешь его сама, поэтому не описывай словами, где он находится («внизу», «справа»);
• "start_tour" — провести по кабинету целиком: role — candidate, employer, fsp (или all — весь сайт). «Покажи кабинет \
кандидата», «я работодатель», «расскажи про сторону Федерации», «что умеет сайт для компании» — это start_tour, \
а не goto на один экран; обзор кабинета начинается с регистрации этой роли;
• "next_section" — идёт обзор, а человеку не интересен текущий раздел («не про это», «пропусти», «это не надо», \
«давай дальше другое»): пропустить его остаток и перейти к следующему разделу обзора; reply — короткая связка с \
названием следующего раздела («Хорошо, тогда кабинет Федерации.»);
• "scroll" — просят показать, что ниже или выше на этом экране («ниже», «пролистай», «наверх»): dir — down, up, top \
или bottom; ты сама пролистаешь и назовёшь блоки, reply — пусто или одна короткая фраза;
• "listen" — человек хочет что-то спросить или сказать, но ещё не сказал: «Слушаю вас.» — и ждёшь;
• "pause" — просит подождать или остановиться; "resume" — продолжить показ: «дальше», «продолжай», «что дальше», \
«веди сама», «рассказывай», «не останавливайся», «сама всё покажи» — всегда resume (если обзор ещё не начинался — \
start_tour с ролью человека); "end" — закончить разговор.
Не повторяй в ответе свои прошлые фразы и реплики сценария — отвечай новыми словами по сути. Просят «сразу кабинет», \
«без регистрации», «к делу» — start_tour (регистрация пропустится сама) или goto на экран кабинета, не на регистрацию. \
Никогда не обещай действий словами («прокручиваю», «вернулась», «открываю») — действие задаётся полем action, а не \
текстом; если подходящего действия нет, честно скажи, что показать это не можешь, и предложи, что можешь. На вопрос о \
блоке экрана объясняй, что он делает и что в нём заполнять или нажимать, — по сути, без общих слов. Не отвечай вопросом \
«что именно вас интересует?» — вместо этого назови два конкретных варианта или сразу объясни самое вероятное. \
Человек хочет остаться на экране и разобраться — не уводи его к обзору; обзор продолжится, когда он скажет «дальше».
Ты экскурсовод: ведёшь сама и не стоишь молча. Не спрашивай «продолжать?» и не жди разрешения идти дальше — после ответа \
показ продолжается сам. В начале разговора ты выясняешь, кто пришёл (кандидат, работодатель или Федерация), и ведёшь \
по его кабинету; если человек из жюри или хочет увидеть всё — role all.
user_name — только если человек прямо назвал своё имя («меня зовут…», «я Анна», «Олег»), в именительном падеже, \
с заглавной буквы; слова вроде «сразу», «давай», «покажи» — не имена. Иначе null.
Просит показать что-то, что есть среди шагов, — выбирай "goto", а не рассказ без показа.

Порядок обзора всего сайта по разделам: главная (home) → кандидат (cand-…, пункты меню по порядку) → работодатель \
(emp-…) → Федерация (fsp-…) → техническое жюри (warroom, val-arena). Между разделами ты спрашиваешь, есть ли вопросы. \
Ты умеешь открыть каждый пункт меню каждого кабинета — все они перечислены ниже как шаги; «подробнее про кандидата / \
работодателя / Федерацию» — это start_tour с role: обзор всех пунктов меню этого кабинета, включая спрятанные под «Ещё». \
Если просят показать то, чего нет среди шагов, честно скажи, что такого экрана нет, и предложи ближайший.

Шаги обзора (для step), по кабинетам и в порядке меню:
{steps}

Примеры:
— «Сколько длится тест?» → «Зависит от ответов: полный режим — от восьми до шестнадцати заданий, экспресс — до семи коротких заданий. \
Показать, где выбирают режим?» (action answer, offer {{"action": "goto", "step": "cand-assessment"}} — покажешь, если \
человек согласится)
— «А как работодатель поймёт, что я не списал?» → «Задания каждый раз генерируются заново, а у попытки есть паспорт \
честности и устная защита. Покажу, как это выглядит.» (action goto, step cand-defense)
— (обзор на разделе работодателя) «Так, подожди, кабинет работодателя, а можно мне не про это?» → «Хорошо, \
работодателя пропустим. Дальше — кабинет Федерации.» (action next_section)
— «Покажи вот, значит, что значит» → «Что именно показать или объяснить?» (action answer)

Формат ответа — две части, без markdown и пояснений. Первая строка — решение одним коротким JSON-объектом: только \
нужные поля, пустые не пиши. Например: {{"action": "answer"}}, {{"action": "goto", "step": "cand-defense"}}, \
{{"action": "start_tour", "role": "employer"}}, {{"action": "answer", "user_name": "Олег"}}. Поля: action, step, point, \
role, user_name, dir, offer, full (true — показать экран целиком). offer — только если ответ заканчивается твоим предложением показать: \
{{"action": "answer", "offer": {{"action": "goto", "step": "cand-assessment"}}}} (или point, start_tour с role).
Со второй строки — то, что ты говоришь вслух, обычным текстом: одна-две фразы.

Карта сайта — всё, о чём у тебя есть знания:
{site_map}"""


def _static_prompt() -> str:
    steps = "\n".join(f"- {k}: {v}" for k, v in STEP_TITLES.items())
    return SYSTEM_STATIC.format(steps=steps, site_map=rag.site_map())


def _dynamic(s: Session | None, *, message: str, name: str | None, role: str | None, path: str, step: str | None,
             touring: bool, paused: bool, screen: dict | None, numbers: dict | None, awaiting: str | None = None,
             last_said: str = "", accepted: str | None = None) -> str:
    shown = [STEP_TITLES.get(x, x) for x in (s.shown if s else [])][-8:]
    tour = ("на паузе" if paused else f"идёт, сейчас шаг «{STEP_TITLES.get(step or '', step or '—')}»" if touring
            else "не идёт")
    said = [h["text"] for h in (s.history if s else []) if h.get("who") == "elena"][-3:]
    if name:
        recent = any(name.lower() in t.lower() for t in said)
        name_hint = (f"Имя звучало в последних репликах — в этом ответе к {name} по имени не обращайся." if recent
                     else f"Можно один раз обратиться по имени «{name}».")
    else:
        # имя спрашивается один раз за разговор — в приветствии; модель его не переспрашивает никогда (решение владельца
        # 21.10). Назвал имя в ответе — верни его в user_name.
        name_hint = ("Имя пока неизвестно — не выдумывай его и не спрашивай. Если человек в этой реплике назвал себя "
                     "(одно-два слова в ответ на вопрос об имени — это имя), верни его в user_name.")
    lines = [
        f"Собеседник: {name or 'имя пока неизвестно'}; роль: {role or 'не выбрана'}; обзор: {tour}. {name_hint}",
        f"Уже показано: {', '.join(shown) if shown else 'пока ничего'}.",
    ]
    sec = section_of(step) if (touring or paused) else None
    if sec:
        nxt = next_section(step)
        lines.append(f"Обзор сейчас в разделе «{SECTION_TITLES[sec]}». Следующий раздел обзора — "
                     f"{'«' + SECTION_TITLES[nxt] + '»' if nxt else 'нет, это последний'}.")
    last_q = (last_said or (s.last_elena if s else "") or "").strip()
    if awaiting and last_q.endswith("?"):
        lines.append(f"Ты только что спросила: «{last_q[:300]}» — и ждёшь ответа. Реплика человека, скорее всего, "
                     "ответ на этот вопрос.")
    if accepted:
        lines.append(f"Человек согласился на твоё предложение «{accepted[:200]}». Выполни его сейчас: action goto на "
                     "подходящий экран или point на элемент; ответ — одна короткая фраза без вопроса.")
    if step and s and step in s.shown:
        lines.append(f"Экран «{STEP_TITLES.get(step, step)}» ты уже показывала: просят подробнее — расскажи больше "
                     "или покажи элемент (point), не открывай этот экран заново.")
    focus = (screen or {}).get("focus") if isinstance(screen, dict) else None
    if isinstance(focus, dict) and focus.get("text"):
        lines.append(f"Блок экрана, о котором, похоже, спрашивают, — «{str(focus.get('heading') or '')[:80]}»: "
                     f"{str(focus['text'])[:700]}. Объясни по нему: что это, зачем и что здесь заполнять или нажимать.")
    if screen:
        title = str(screen.get("title") or "").strip()[:120]
        items = [str(x).strip()[:60] for x in (screen.get("items") or []) if str(x).strip()][:28]
        lines.append(f"Экран сейчас: {path} — {title or 'без заголовка'}.")
        if items:
            lines.append("Элементы на экране: " + "; ".join(f"«{x}»" for x in items) + ".")
    else:
        lines.append(f"Экран сейчас: {path}.")
    if s and (s.notes or s.suggest):
        hint = s.notes
        if s.suggest and s.suggest in STEP_TITLES and s.suggest not in s.shown:
            hint += f" Стоит показать дальше: {s.suggest} ({STEP_TITLES[s.suggest]})."
        if s.tone in ("slower", "simpler"):
            hint += " Говори проще и короче."
        lines.append(f"Подсказка наставника (учитывай, но прежде всего отвечай на то, что человек сказал сейчас): {hint.strip()}")
    extra = str((screen or {}).get("title") or "")
    chunks = rag.retrieve(message, current_path=path, step=step, extra_text=extra)
    know = [f"[{c.id}] {c.body()}" for c in chunks]
    if numbers:
        know.append(f"[validation_numbers] {numbers.get('content', '')}")
    lines.append("Знания:\n" + "\n".join(know))
    lines.append("Ответ: первая строка — короткий JSON решения (только нужные поля), со второй — то, что ты говоришь вслух.")
    return "\n".join(lines)


def build_messages(message: str, *, sid: str | None, name: str | None, role: str | None, path: str, step: str | None,
                   touring: bool, paused: bool, screen: dict | None, history: list[dict] | None,
                   numbers: dict | None = None, awaiting: str | None = None, last_said: str = "",
                   accepted: str | None = None) -> list[dict]:
    """Подсказка хода: постоянная часть (кэшируется) + состояние разговора и экрана + история."""
    s = session(sid)
    dyn = _dynamic(s, message=message, name=name, role=role, path=path, step=step, touring=touring, paused=paused,
                   screen=screen, numbers=numbers, awaiting=awaiting, last_said=last_said, accepted=accepted)
    return _messages(s, dyn, message, history)


def _messages(s: Session | None, dyn: str, message: str, history: list[dict] | None) -> list[dict]:
    msgs: list[dict] = [
        {"role": "system", "content": [
            {"type": "text", "text": _static_prompt(), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dyn},
        ]},
    ]
    hist = (s.history if s and s.history else history) or []
    for h in hist[-12:]:
        who = "assistant" if h.get("who") == "elena" else "user"
        c = str(h.get("text") or "").strip()
        if c:
            if msgs[-1]["role"] == who and who != "system":
                msgs[-1]["content"] = f"{msgs[-1]['content']} {c[:400]}"
            else:
                msgs.append({"role": who, "content": c[:400]})
    if msgs[-1]["role"] == "user":
        msgs[-1]["content"] = f"{msgs[-1]['content']} {message.strip()[:600]}"
    else:
        msgs.append({"role": "user", "content": message.strip()[:600]})
    return msgs


def _flat(msgs: list[dict]) -> list[dict]:
    """Для моделей без кэша подсказки: системная часть — одной строкой."""
    out = []
    for m in msgs:
        c = m["content"]
        if isinstance(c, list):
            c = "\n\n".join(x.get("text", "") for x in c)
        out.append({"role": m["role"], "content": c})
    return out


_HTTP = None
_HTTP_LOCK = threading.Lock()


def _client():
    """Один клиент на процесс: соединение с ретранслятором переиспользуется (минус рукопожатие на каждом ходе)."""
    global _HTTP
    with _HTTP_LOCK:
        if _HTTP is None:
            import httpx

            from app.core.config import get_settings
            from app.modules.llm import client as llm

            _HTTP = httpx.Client(timeout=httpx.Timeout(20, connect=6), transport=llm._TRANSPORT,
                                 verify=llm._verify("openrouter", get_settings()),
                                 limits=httpx.Limits(max_connections=16, max_keepalive_connections=8,
                                                     # по умолчанию httpx закрывает простаивающее соединение через 5 с —
                                                     # ход раз в 20–40 с платил рукопожатием (решение 3,8–6 с вместо 1,5–2)
                                                     keepalive_expiry=float(os.environ.get("CONCIERGE_KEEPALIVE_S", "240"))))
        return _HTTP


TURN_SCHEMA = {"type": "json_schema", "json_schema": {"name": "elena_turn", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["reply", "action", "step", "point", "role", "user_name", "dir"],
    "properties": {
        "reply": {"type": "string"},
        "action": {"type": "string", "enum": ["answer", "goto", "point", "start_tour", "next_section", "pause", "resume", "end", "scroll"]},
        "step": {"type": ["string", "null"]}, "point": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]}, "user_name": {"type": ["string", "null"]},
        "dir": {"type": ["string", "null"]},
    }}}}

_REPLY_RE = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)')
_FIELD_RE = re.compile(r'"(action|step|point|role|user_name|dir)"\s*:\s*"([^"]*)"')


def _salvage(text: str) -> dict | None:
    """Ответ оборвался или пришёл не чистым JSON — достаём reply и поля по отдельности."""
    m = _REPLY_RE.search(text or "")
    if not m:
        return None
    try:
        reply = json.loads('"' + m.group(1) + '"')
    except ValueError:
        reply = m.group(1)
    d: dict = {"reply": reply}
    for k, v in _FIELD_RE.findall(text):
        d[k] = v
    return d


def _ask(msgs: list[dict], spec: str, timeout: float, max_tokens: int = 420, schema: dict | None = None) -> dict | None:
    import httpx

    from app.core.config import get_settings
    from app.modules.llm import client as llm

    prov, _, rest = spec.partition("=")
    if not rest:
        prov, rest = "openrouter", spec
    model, _, effort = rest.partition("@")
    use = msgs if model.startswith("anthropic/") else _flat(msgs)
    t0 = time.monotonic()
    try:
        url, headers, extra = llm._endpoint(prov, get_settings())
        body = {"model": model, "messages": use, "temperature": 0.35, "max_tokens": max_tokens, **extra}
        if effort.startswith("~") and effort[1:].isdigit():
            body["reasoning"] = {"max_tokens": int(effort[1:])}   # короткое рассуждение с потолком
            body["max_tokens"] = max_tokens + int(effort[1:])
        elif effort:
            body["reasoning"] = {"effort": effort}
        if schema:
            body["response_format"] = schema
        r = _client().post(url, headers=headers, json=body, timeout=httpx.Timeout(max(1.0, timeout), connect=5))
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            log.warning("concierge llm %s: HTTP %s за %d мс", model, r.status_code, ms)
            return None
        j = r.json()
        ch = (j.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        text = msg.get("content") or ""
        data = llm._extract_json(text) if text.strip() else None
        if not isinstance(data, dict):
            data = _salvage(text)
        if not isinstance(data, dict) and schema and text.strip() and "{" not in text and "<" not in text:
            data = {"reply": text.strip(), "action": "answer"}  # ответ простым текстом — тоже ответ
        if not isinstance(data, dict):
            log.warning("concierge llm %s: нет JSON за %d мс (finish=%s, out=%s): %r", model, ms, ch.get("finish_reason"),
                        (j.get("usage") or {}).get("completion_tokens"), text[:160])
            return None
        data["_model"] = model
        log.info("concierge llm %s: ответ за %d мс", model, ms)
        return data
    except Exception as e:  # noqa: BLE001 — сбой модели не роняет разговор, будет откат
        log.warning("concierge llm %s: %s за %d мс", model, type(e).__name__, int((time.monotonic() - t0) * 1000))
        return None


# Замеры 20.10 на полной подсказке: Sonnet 5 — 2,9–4,6 с, Gemini 2.5 Flash — 1,4–1,5 с. Ждём Sonnet 2,4 с, дальше берём
# готовый ответ страховки: живой разговор важнее лишних полутора секунд. Больше качества — поднять CONCIERGE_LLM_PREFER_S.
LLM_PREFER_S = float(os.environ.get("CONCIERGE_LLM_PREFER_S", "1.2"))


def answer(message: str, *, sid: str | None, name: str | None, role: str | None, path: str, step: str | None,
           touring: bool, paused: bool, screen: dict | None, history: list[dict] | None,
           numbers: dict | None = None, awaiting: str | None = None, last_said: str = "",
           accepted: str | None = None) -> dict | None:
    """Ответ модели. Модели спрашиваются сразу: берём первый ответ основных (первые LLM_PRIMARY_N в LLM_MODELS); если
    ни одна основная не ответила за LLM_PREFER_S — лучший из пришедших (по порядку в списке)."""
    s = session(sid)
    dyn = _dynamic(s, message=message, name=name, role=role, path=path, step=step, touring=touring, paused=paused,
                   screen=screen, numbers=numbers, awaiting=awaiting, last_said=last_said, accepted=accepted)
    msgs = _messages(s, dyn, message, history)
    models = list(LLM_MODELS)
    if not models:
        return None
    t0 = time.monotonic()
    deadline = t0 + LLM_DEADLINE_S

    def ok(d: dict | None) -> bool:
        return bool(d and isinstance(d.get("reply"), str) and d["reply"].strip())

    futs = {_POOL.submit(_ask, msgs, spec, LLM_DEADLINE_S - 0.3, 420, TURN_SCHEMA): k for k, spec in enumerate(models[:3])}
    got: dict[int, dict] = {}
    pending = set(futs)
    while pending and time.monotonic() < deadline:
        now = time.monotonic()
        prefer_left = t0 + LLM_PREFER_S - now
        if any(k < max(1, LLM_PRIMARY_N) for k in got):
            break
        if prefer_left <= 0 and got:
            break
        done, pending = wait(pending, timeout=max(0.05, min(deadline - now, prefer_left if prefer_left > 0 else deadline - now)),
                             return_when=FIRST_COMPLETED)
        for f in done:
            d = f.result()
            if ok(d):
                got[futs[f]] = d
    if not got:
        return None
    prim = [k for k in got if k < max(1, LLM_PRIMARY_N)]
    k = prim[0] if prim else min(got)
    d = got[k]
    d["_ms"] = int((time.monotonic() - t0) * 1000)
    return d


# ------------------------------------------------------------------ наставник

SUPERVISOR_PROMPT = """Ты — наставник голосового ИИ-проводника Насти на сайте платформы найма «Драфт». Настя ведёт \
человека по сайту и отвечает на вопросы. Прочитай состояние и стенограмму и дай Насте подсказку на следующий ход.

Шаги обзора:
{steps}

Верни строго JSON:
{{"notes": "до 200 знаков: кто собеседник и что ему важно, на какой его вопрос ответ был неполным. Это наблюдения, \
а не команды: что и когда показать, решает Настя по ходу разговора", "suggest_step": "id шага, который стоит показать \
дальше, или null", "tone": "normal|slower|simpler"}}
tone "slower" или "simpler" — только если человек явно путается, переспрашивает или просит медленнее."""


def _supervise(sid: str) -> None:
    try:
        s = session(sid)
        if s is None:
            return
        hist = "\n".join(f"{'Настя' if h['who'] == 'elena' else 'Человек'}: {h['text']}" for h in s.history[-18:])
        state = (f"Имя: {s.name or 'неизвестно'}; роль: {s.role or 'не выбрана'}; показано: "
                 f"{', '.join(s.shown) or 'ничего'}.")
        steps = "\n".join(f"- {k}: {v}" for k, v in STEP_TITLES.items())
        msgs = [{"role": "system", "content": SUPERVISOR_PROMPT.format(steps=steps)},
                {"role": "user", "content": f"{state}\n\nСтенограмма:\n{hist}"}]
        d = _ask(msgs, SUPERVISOR_MODEL, 30.0, max_tokens=1200)
        with mutate(sid) as m:
            if m is None:
                return
            m.sup_at = 0.0
            if d:
                m.notes = str(d.get("notes") or "").strip()[:260]
                sug = d.get("suggest_step")
                m.suggest = sug if isinstance(sug, str) and sug in STEP_TITLES else None
                m.tone = d.get("tone") if d.get("tone") in ("normal", "slower", "simpler") else "normal"
        if d and m is not None:
            write(m, "coach", m.notes, suggest=m.suggest, tone=m.tone, model=d.get("_model"))
    except Exception as e:  # noqa: BLE001 — наставник не мешает разговору
        log.warning("concierge supervisor: %s", type(e).__name__)


def supervise_async(sid: str | None) -> None:
    if not SUPERVISOR_MODEL:
        return
    with mutate(sid) as s:
        if s is None or len(s.history) < 2 or (s.sup_at and time.time() - s.sup_at < 45):
            return
        s.sup_at = time.time()
    _SUP_POOL.submit(_supervise, s.sid)

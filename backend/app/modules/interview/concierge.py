"""Живой ИИ-проводник Елена с базой знаний RAG по всей платформе «Драфт» и языковой моделью через OpenRouter.

Возможности:
1. avatar_token() — одноразовый токен потока Anam (cara-4, enableAudioPassthrough=True, videoQuality=high) + TURN-серверы;
2. cached_speak(text, fmt) — синтез речи ElevenLabs (mp3 и pcm_16000 для липсинка Anam) с кэшем в памяти и на диске (/tmp/concierge_tts_cache);
3. transcribe(audio, mime) — распознавание русской речи через Deepgram Nova-2;
4. reply_chat(...) — мгновенный (< 10 мс) ответ на знакомство, выбор роли и команды навигации + RAG-диалог через OpenRouter LLM по вопросам о платформе.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
from typing import Literal

from app.modules.interview import port as pt

_TTS_CACHE_DIR = Path(os.environ.get("CONCIERGE_TTS_CACHE_DIR", "/tmp/concierge_tts_cache"))

# Полная база знаний RAG по всем экранам, кнопкам, полям и алгоритмам платформы «Драфт»
RAG_CHUNKS: list[dict[str, str]] = [
    {
        "id": "landing",
        "paths": "/",
        "keywords": "главная витрина закон драфт почему резюме обратный найм старт вход регистрация ползунок",
        "content": (
            "Экран: Главная страница (/). "
            "На первом экране слева — заголовок и две кнопки быстрого входа («Войти как кандидат» и «Войти как работодатель»), "
            "справа — интерактивная витрина «Обратный драфт в действии»: можно переключать направления (Backend, Frontend, Data/ML, DevOps/SRE, ИБ, Мобильная), "
            "двигать ползунок зарплатного предложения и нажать «Попробовать пригласить». "
            "Ниже расположен блок «Почему резюме больше не работает: 4 закона Драфта» с тремя вкладками: Работодатель, Кандидат и Федерация спортивного программирования. "
            "Ещё ниже — секция «Как это работает: 3 контура под капотом» и отдельные маршруты из 5 шагов для кандидатов и для работодателей."
        ),
    },
    {
        "id": "candidate_overview",
        "paths": "/candidate",
        "keywords": "кабинет кандидата обзор дорожная карта шаг маршрут роль выйти",
        "content": (
            "Экран: Кабинет кандидата — Обзор (/candidate). "
            "В самом верху закреплена панель быстрого переключения ролей в один клик (Кандидат, Тест с нуля, Работодатель, Федерация ФСП) и кнопка «Выйти». "
            "В центре — «Дорожная карта кандидата» из 4 последовательных шагов: "
            "Шаг 1 — Направление и стек технологий (кнопка «Открыть опрос и стек»); "
            "Шаг 2 — Адаптивный тест на грейд (кнопка «К выбору грейда и тесту»); "
            "Шаг 3 — Живая устная защита кода с ИИ-аватаром (3-минутный разговор голосом по решённым задачам для подтверждения самостоятельности ответа, кнопка «Поговорить с ИИ-аватаром вживую»); "
            "Шаг 4 — Карта роста и приглашения с зарплатой (кнопки «Карта навыков и рост» и «Приглашения»). "
            "Ниже — переключатель готовности к предложениям и три карточки статистики: Категория, Приглашения и Задания с вилкой."
        ),
    },
    {
        "id": "candidate_assessment",
        "paths": "/candidate/assessment /candidate/express",
        "keywords": "тест грейд опрос стажёр junior middle senior lead principal согласие галочка начать экспресс полный античит",
        "content": (
            "Экран: Опрос и тест на грейд (/candidate/assessment). "
            "На первом экране сразу под заголовком расположены 6 карточек выбора целевого грейда: Стажёр, Junior, Middle, Senior, Lead и Principal. "
            "Текущий подтверждённый грейд отмечен зелёной плашкой «Ваш грейд», а для повышения предвыбран следующий уровень (Senior). "
            "Прямо под карточками находится розовый блок запуска теста: нужно поставить галочку согласия на проверку самостоятельности выполнения и нажать кнопку «Начать тест» (рядом — кнопка «Добавить второе направление»). "
            "Ниже — переключатель «Режим теста»: можно выбрать «Полный тест · 8–16 + до 6 у порога» (до 80 минут) или быстрый режим «Экспресс-калибровка · 5 минут» (5–7 коротких адаптивных задач того же банка из 403 семейств и 8 060 вариантов)."
        ),
    },
    {
        "id": "candidate_feedback",
        "paths": "/candidate/feedback /candidate/category",
        "keywords": "карта навыков рост шкала irt тета психометрия пробелы рынок hh вакансии маршрут задачи фишер",
        "content": (
            "Экран: Карта навыков и рост (/candidate/feedback). "
            "Вверху — 4 карточки сводки: Категория, Уверенно, Пробелы и Достоверность. "
            "Под ними — визуальная шкала «Психометрия 2PL IRT» от -2,5 до +2,5 с зонами грейдов, точкой способности тета и доверительным коридором погрешности. "
            "Ниже — розовый блок «Маршрут роста: что сделать дальше», где напротив каждого шага есть прямая кнопка («Добавить в стек опроса», «Задачи с автопроверкой», «К тесту на грейд»). "
            "Далее идёт таблица «Что показал тест» по темам и блок «Что сейчас просит рынок» на основе 1 344 открытых вакансий hh.ru по направлению в России."
        ),
    },
    {
        "id": "candidate_invitations_fsp",
        "paths": "/candidate/invitations /candidate/fsp /candidate/assignments",
        "keywords": "приглашения оффер вилка зарплата принять отклонить контакты паспорт фсп достижения кубок задания",
        "content": (
            "Экраны: Приглашения (/candidate/invitations), Паспорт ФСП (/candidate/fsp) и Задания (/candidate/assignments). "
            "В разделе «Приглашения» кандидат видит предложения от работодателей: компания обязана сразу указать зарплатную вилку «от — до» в рублях. "
            "Кандидат видит индекс доверия компании и список причин выбора, и может нажать «Принять» (только тогда открываются имя и телефон), «Отклонить» или «Предложить свою вилку». "
            "В разделе «Паспорт ФСП» отображаются верифицированные спортивные достижения из реестра Федерации спортивного программирования и индекс достижений ФСП."
        ),
    },
    {
        "id": "employer_needs",
        "paths": "/employer/needs /employer",
        "keywords": "работодатель компания потребность вакансия текст разобрать ст 64 тк рф подборка кандидаты формула ранжирование",
        "content": (
            "Экран: Кабинет работодателя — Потребности и подборки (/employer/needs). "
            "Вверху — дорожная карта работодателя из 4 шагов: 1. Текст вакансии, 2. Авторазбор и ТК РФ, 3. Подборка 2PL IRT + ФСП, 4. Приглашение с вилкой. "
            "Ниже — поле «Кого вы ищете»: можно вставить описание вакансии своими словами, надиктовать голосом, загрузить файл или нажать «Подставить пример», а затем нажать «Разобрать требования». "
            "Система автоматически выделяет обязательный и желательный стек с цитатами, сверяет зарплату с рынком hh.ru и удаляет дискриминационные формулировки по ст. 64 ТК РФ. "
            "На странице готовой подборки (/employer/needs/:id) над карточками кандидатов показана полоса формулы ранжирования: 45 % — тест 2PL IRT, 35 % — обязательный стек, 10 % — реестр ФСП, 5 % — проверочные задачи, 5 % — желательный стек."
        ),
    },
    {
        "id": "employer_compare",
        "paths": "/employer/compare",
        "keywords": "сравнение сравнить советник руководителя таблица матрица лидер пригласить",
        "content": (
            "Экран: Сравнение кандидатов и ИИ-советник руководителя (/employer/compare и /employer/needs/:id/compare). "
            "Вверху страницы расположена панель «ИИ-советник руководителя»: она выдаёт сводный доклад по сравниваемым кандидатам (кто лидер по подтверждённому тесту и паспорту ФСП, у кого лучше соотношение навыков и зарплатной вилки, о чём спросить на финальном созвоне). "
            "Ниже — подробная таблица сравнения по каждому требованию вакансии с подсветкой лучших показателей и кнопками «Пригласить» и «Задание всем»."
        ),
    },
    {
        "id": "fsp_cabinet",
        "paths": "/fsp",
        "keywords": "фсп федерация спортивного программирования аналитика спрос регионы эффект соревнований зарплаты кубки",
        "content": (
            "Экран: Кабинет Федерации спортивного программирования (/fsp). "
            "Содержит аналитические вкладки по всей экосистеме: «Обзор», «Спрос работодателей» (тепловая карта востребованных и дефицитных навыков по регионам России), "
            "«Эффект соревнований» (статистика того, как победы и разряды ФСП увеличивают число приглашений и предлагаемые зарплатные вилки), "
            "«Зарплаты в офферах», «Воронка категорий» и «Кубки» (отборочные соревнования под задачи работодателей)."
        ),
    },
]


def retrieve_rag(query: str, current_path: str) -> str:
    """Подбирает знания о текущем экране + наиболее близкие разделы по словам запроса."""
    q_words = set(re.findall(r"[а-яёa-z0-9]{3,}", (query or "").lower()))
    scored: list[tuple[int, dict[str, str]]] = []
    for ch in RAG_CHUNKS:
        score = 0
        paths = ch["paths"].split()
        if any(current_path == p or (p != "/" and current_path.startswith(p)) for p in paths):
            score += 100
        kw = ch["keywords"] + " " + ch["content"].lower()
        for w in q_words:
            if w in kw:
                score += 10
        scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [ch["content"] for sc, ch in scored[:3] if sc > 0] or [RAG_CHUNKS[0]["content"]]
    return "\n\n".join(picked)


SYSTEM_PROMPT = """Ты — Елена, живой голосовой ИИ-проводник платформы обратного найма «Драфт».
Ты общаешься с человеком живым голосом (твои слова озвучиваются голосом и синхронизируются с губами видеоаватара).

Правила твоего поведения:
1. Говори тепло, интеллигентно, энергично и кратко: строго 1–2 предложения за один раз (до 220 знаков), ТОЛЬКО чистым русским текстом для озвучки вслух (без списков, звёздочек, решёток и кавычек).
2. Знакомство и диалог:
   - Если собеседник назвал имя — запомни его в поле "user_name" и обращайся по имени.
   - Если собеседник назвал только имя без роли — поставь "action": "ask_role" и вежливо спроси по имени, в какой роли показать платформу (кандидат, работодатель, ФСП или весь сайт целиком).
   - Если собеседник назвал роль или попросил начать — поставь "action": "start_tour", укажи "detected_role" ("all", "candidate", "employer" или "fsp") и скажи, что сейчас на главной странице нажмёшь нужные кнопки и проведёшь по кабинету.
   - Если собеседник задал конкретный вопрос — дай точный, короткий ответ в 1–2 предложениях строго по базе знаний RAG ниже и поставь "action": "continue_tour".
3. Никогда не упоминай внутренние названия чужих сервисов (не говори слова ElevenLabs, Anam, Deepgram, OpenRouter, WebRTC). Говори продуктовым языком.

Верни ответ СТРОГО в формате JSON:
{
  "reply": "Твоя короткая устная реплика (1-2 предложения чистым текстом)",
  "user_name": "Имя собеседника с заглавной буквы или null",
  "detected_role": "all" | "candidate" | "employer" | "fsp" | null,
  "action": "ask_role" | "start_tour" | "continue_tour",
  "jump_to_step": число от 0 до 9 или null
}"""

_NAME_RE = re.compile(
    r"(?:меня\s+зовут|я\s+—|я\s+-|мо[её]\s+имя|зови\s+меня|обращайся\s+ко\s+мне|это)\s+([А-ЯЁа-яёA-Za-z]{2,20})",
    re.I,
)
_SIMPLE_NAME_RE = re.compile(
    r"^\s*(?:привет[\s,!.]*|здравствуйте[\s,!.]*|добрый\s+день[\s,!.]*)?(?:я\s+)?([А-ЯЁа-яё]{2,18})(?:[\s,!.]+(?:я|мне|покажи|кандидат|работодатель|жюри|эксперт|давай|привет|хочу|интерес).*)?$",
    re.I,
)
_STOP_NAMES = {
    "привет", "здравствуйте", "добрый", "покажи", "расскажи", "кандидат", "работодатель",
    "компания", "федерация", "эксперт", "жюри", "давай", "хочу", "кто", "что", "как", "где",
    "зачем", "почему", "дальше", "стоп", "пауза", "весь", "сайт", "просто", "ничего", "алло",
    "начинай", "начнем", "начнём", "поехали", "открой", "перейди", "тест", "вакансии",
}

_QUESTION_MARKERS = (
    "?", "почему", "зачем", "сколько", "откуда", "какой", "какая", "какие", "каким",
    "чем ", "расскажи", "объясни", "формул", "античит", "психометр", "irt", "фишер",
    "безопасн", "пдн", "152", "ст 64", "утечк", "инъекц", "поток", "аватар", "голос",
)


def extract_name(text: str, current_name: str | None = None) -> str | None:
    if current_name:
        return current_name
    t = (text or "").strip()
    m = _NAME_RE.search(t)
    if m:
        cand = m.group(1).strip().capitalize()
        if cand.lower() not in _STOP_NAMES:
            return cand
    m2 = _SIMPLE_NAME_RE.match(t)
    if m2:
        cand = m2.group(1).strip().capitalize()
        if cand.lower() not in _STOP_NAMES:
            return cand
    return None


def detect_role(text: str) -> Literal["all", "candidate", "employer", "fsp"] | None:
    t = (text or "").lower()
    if any(w in t for w in ("работодат", "компан", "нанима", "эйчар", "hr", "ваканс", "подборк", "директор", "руководит")):
        return "employer"
    if any(w in t for w in ("фсп", "федерац", "аналитик", "спорт")):
        return "fsp"
    if any(w in t for w in ("кандидат", "разработч", "соискат", "специалист", "инженер", "работ")):
        return "candidate"
    if any(w in t for w in ("жюри", "эксперт", "весь", "всё", "все", "полн", "сначала", "давай", "начин", "покажи", "экскурс", "обзор", "поехали")):
        return "all"
    return None


def detect_step_jump(text: str) -> int | None:
    t = (text or "").lower()
    if "тест" in t or "опрос" in t or "грейд" in t:
        return 4
    if "карт" in t or "навык" in t or "шкал" in t or "irt" in t:
        return 5
    if "приглаш" in t or "оффер" in t or "вилк" in t:
        return 6
    if "потребн" in t or "ваканс" in t:
        return 7
    if "сравн" in t or "советник" in t:
        return 8
    if "фсп" in t or "федерац" in t:
        return 9
    return None


def is_substantive_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) > 95:
        return True
    return any(m in t for m in _QUESTION_MARKERS)


@lru_cache(maxsize=256)
def cached_speak(text: str, fmt: Literal["mp3", "pcm_16000"]) -> tuple[bytes, str]:
    clean = " ".join((text or "").split()).strip()
    mime = "audio/pcm" if fmt == "pcm_16000" else "audio/mpeg"
    key = hashlib.sha256(f"{fmt}:{clean}".encode("utf-8")).hexdigest()[:32]
    try:
        _TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fp = _TTS_CACHE_DIR / f"{key}.{fmt}.bin"
        if fp.exists() and fp.stat().st_size > 100:
            return fp.read_bytes(), mime
    except Exception:
        fp = None

    audio, actual_mime, _usd = pt.get_port().speak(clean, fmt)
    if fp is not None and audio and len(audio) > 100:
        try:
            fp.write_bytes(audio)
        except Exception:
            pass
    return audio, actual_mime or mime


def _fast_role_reply(name: str | None, role: Literal["all", "candidate", "employer", "fsp"], jump: int | None) -> dict:
    prefix = f"Приятно познакомиться, {name}. " if name else "Отлично. "
    if role == "candidate":
        reply = (
            f"{prefix}Начнём прямо с главной страницы: сейчас я наглядно нажму кнопку входа кандидата "
            "и проведу вас по всем шагам и кнопкам личного кабинета."
        )
    elif role == "employer":
        reply = (
            f"{prefix}Начнём прямо с главной страницы: сейчас я покажу интерактивную карточку с вилкой, "
            "нажму кнопку входа работодателя и проведу вас по разбору вакансии и сравнению кандидатов."
        )
    elif role == "fsp":
        reply = (
            f"{prefix}Начнём с главной страницы: сейчас я нажму вкладку Федерации спортивного программирования, "
            "а затем открою кабинет аналитики ФСП."
        )
    else:
        reply = (
            f"{prefix}Начнём с главной страницы: я буду по шагам нажимать кнопки и вкладки "
            "и проведу вас через все разделы и кабинеты платформы."
        )
    return {
        "reply": reply,
        "user_name": name,
        "detected_role": role,
        "start_tour": True,
        "jump_to_step": jump,
    }


def reply_chat(
    message: str,
    *,
    user_name: str | None = None,
    user_role: str | None = None,
    current_path: str = "/",
    step_index: int = 0,
    history: list[dict] | None = None,
) -> dict:
    fallback_name = extract_name(message, user_name)
    detected_now = detect_role(message)
    fallback_role = detected_now or (user_role if user_role in ("all", "candidate", "employer", "fsp") else None)
    fallback_jump = detect_step_jump(message)

    # 1. Мгновенный ответ (< 5 мс без ожидания LLM) при знакомстве, выборе роли и прямых командах навигации
    if not is_substantive_question(message):
        if fallback_name and not detected_now and (not history or len(history) <= 2):
            return {
                "reply": (
                    f"Очень приятно познакомиться, {fallback_name}. "
                    "Скажите, в какой роли вам показать платформу — как кандидату, как работодателю или пройти весь сайт целиком?"
                ),
                "user_name": fallback_name,
                "detected_role": "all",
                "start_tour": False,
                "jump_to_step": None,
            }
        if detected_now or fallback_jump is not None:
            return _fast_role_reply(fallback_name, fallback_role or "all", fallback_jump)

    # 2. Содержательный вопрос пользователя по экрану/алгоритмам — быстрый вызов LLM с базой знаний RAG
    rag_context = retrieve_rag(message, current_path)
    state_summary = (
        f"Текущее состояние: имя собеседника = {fallback_name or 'неизвестно'}, "
        f"выбранная роль = {fallback_role or 'не выбрана'}, "
        f"текущий адрес экрана = {current_path}, шаг маршрута = {step_index + 1} из 10.\n\n"
        f"База знаний RAG по текущему экрану и вопросу:\n{rag_context}"
    )

    msgs: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + state_summary},
    ]
    for h in (history or [])[-6:]:
        w = "assistant" if h.get("who") == "elena" else "user"
        c = str(h.get("text") or "").strip()
        if c:
            msgs.append({"role": w, "content": c[:400]})
    msgs.append({"role": "user", "content": message.strip()[:600]})

    try:
        from app.modules.llm import client as llm

        res = llm.chat(
            msgs,
            temperature=0.3,
            max_tokens=170,
            want_json=True,
            model=None,
            timeout_s=7.0,
        )
        if res.ok and isinstance(res.data, dict) and isinstance(res.data.get("reply"), str):
            d = res.data
            clean_reply = re.sub(r"[*#`_~]+", "", str(d["reply"])).strip()
            clean_reply = " ".join(clean_reply.split())
            llm_name = d.get("user_name") if isinstance(d.get("user_name"), str) and len(d.get("user_name").strip()) >= 2 else None
            final_name = llm_name or fallback_name
            llm_role = d.get("detected_role") if d.get("detected_role") in ("all", "candidate", "employer", "fsp") else None
            final_role = llm_role or fallback_role
            action = d.get("action") if d.get("action") in ("ask_role", "start_tour", "continue_tour") else None
            if not action:
                action = "start_tour" if final_role else "ask_role"
            jmp = d.get("jump_to_step") if isinstance(d.get("jump_to_step"), int) and 0 <= d.get("jump_to_step") <= 9 else fallback_jump
            return {
                "reply": clean_reply[:420],
                "user_name": final_name,
                "detected_role": final_role or "all",
                "start_tour": action != "ask_role",
                "jump_to_step": jmp,
            }
    except Exception:
        pass

    return _fast_role_reply(fallback_name, fallback_role or "all", fallback_jump)

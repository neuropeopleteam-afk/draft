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
import json
import os
from pathlib import Path
import re
from typing import Literal

from app.modules.interview import port as pt

TOUR_STEPS_TOTAL = 13  # шагов в TOUR_STEPS (frontend/src/components/InteractiveAvatarTour.tsx)
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


# --- Актуальные цифры платформы для ответов Елены (KF4) ---
# Источник — docs/NUMBERS.json (собирает tools/publish/gen_numbers.py); дополнение и сверка по свежести — снимок бенчмарка
# backend/app/modules/validation/data/matching_bench.json (make bench; есть и в образе backend). Нет файлов — fallback
# на снимок 20.10.2026 ниже. Никаких захардкоженных цифр в тексте базы знаний: всё подставляется отсюда.
_HERE = Path(__file__).resolve()
_BENCH_JSON = _HERE.parents[1] / "validation" / "data" / "matching_bench.json"
_ACCURACY_JSON = _HERE.parents[1] / "validation" / "data" / "accuracy_views.json"


def _numbers_paths() -> list[Path]:
    env = os.environ.get("CONCIERGE_NUMBERS_PATH")
    out = [Path(env)] if env else []
    for up in (4, 3):  # репозиторий: backend/app/modules/interview → корень; в образе backend — /app/docs (если смонтирован)
        if len(_HERE.parents) > up:
            out.append(_HERE.parents[up] / "docs" / "NUMBERS.json")
    return out


NUMBERS_FALLBACK: dict[str, float | int | str] = {  # снимок make bench 20.10.2026 (банк 4d44), accuracy_views 19.10.2026
    "as_of": "2026-10-20", "p5": 0.751, "p10": 0.725, "mrr": 0.896, "ndcg10": 0.566, "recall30": 0.24,
    "p5_vs_bm25": 0.31, "p10_vs_bm25": 0.294, "inflated_top10": 0.069, "inflated_top10_bm25": 0.32,
    "within1_one_session": 0.9936, "within1_retest": 0.998, "far_from_cut": 0.8338, "no_under_claim": 0.8215,
    "two_stage": 0.694, "attacks_n": 116, "attacks_passed": 0, "demo_candidates": 860,
}


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except Exception:
        return None


def _mtimes() -> tuple:
    return tuple(p.stat().st_mtime if p.is_file() else 0.0 for p in (*_numbers_paths(), _BENCH_JSON, _ACCURACY_JSON))


@lru_cache(maxsize=4)
def _live_numbers_cached(_key: tuple) -> dict:
    out: dict = dict(NUMBERS_FALLBACK)
    out["source"] = "снимок по умолчанию"
    nums = next((d for d in (_read_json(p) for p in _numbers_paths()) if d), None)
    if nums:
        m = nums.get("matching") or {}
        for k in ("p5", "p10", "mrr", "ndcg10"):
            if isinstance((m.get(k) or {}).get("mean"), (int, float)):
                out[k] = m[k]["mean"]
        rc = m.get("recall30") or m.get("recall@30")
        if isinstance(rc, dict) and isinstance(rc.get("mean"), (int, float)):
            out["recall30"] = rc["mean"]
        v = (nums.get("grade_accuracy") or {}).get("views") or {}
        for k, src, fld in (("far_from_cut", "far_from_cut", "exact"), ("no_under_claim", "no_under_claim", "exact"),
                            ("within1_retest", "strict_pool", "within_1")):
            if isinstance((v.get(src) or {}).get(fld), (int, float)):
                out[k] = v[src][fld]
        dc = (nums.get("demo") or {}).get("candidates")
        if isinstance(dc, int) and dc > 0:
            out["demo_candidates"] = dc
        out["as_of"] = str(m.get("generated_at") or out["as_of"])[:10]
        out["source"] = "docs/NUMBERS.json"
        out["_numbers_at"] = str(m.get("generated_at") or "")
    bench = _read_json(_BENCH_JSON)
    if bench and not bench.get("missing"):
        bm, pm = bench.get("metrics") or {}, bench.get("paired_platform_minus") or {}
        pl = bm.get("platform") or {}
        fresher = str(bench.get("generated_at") or "") > out.get("_numbers_at", "")
        pairs = {"p5": "p@5", "p10": "p@10", "mrr": "mrr", "ndcg10": "ndcg@10", "recall30": "recall@30"}
        for k, mk in pairs.items():
            val = (pl.get(mk) or {}).get("mean")
            if isinstance(val, (int, float)) and (fresher or k == "recall30" and "recall30" not in (nums or {}).get("matching", {})):
                out[k] = val
        for k, mk in (("p5_vs_bm25", "p@5"), ("p10_vs_bm25", "p@10")):
            val = ((pm.get("bm25") or {}).get(mk) or {}).get("mean")
            if isinstance(val, (int, float)):
                out[k] = val
        infl = (bench.get("groups") or {}).get("inflated") or {}
        for k, src in (("inflated_top10", "platform"), ("inflated_top10_bm25", "bm25")):
            val = (infl.get(src) or {}).get("irrelevant_inflated_top10")
            if isinstance(val, (int, float)):
                out[k] = val
        if fresher:
            out["as_of"] = str(bench.get("generated_at"))[:10]
            out["source"] = (out["source"] + " + " if nums else "") + "бенчмарк make bench"
    acc = _read_json(_ACCURACY_JSON)
    if acc:
        for k, path in (("within1_one_session", ("one_session_metrics", "within_1")), ("two_stage", ("two_stage_metrics", "exact"))):
            val = (acc.get(path[0]) or {}).get(path[1])
            if isinstance(val, (int, float)):
                out[k] = val
    out.pop("_numbers_at", None)
    return out


def live_numbers() -> dict:
    """Актуальные цифры (доли 0…1): NUMBERS.json → бенчмарк → fallback. Кэш сбрасывается при изменении файлов."""
    try:
        return _live_numbers_cached(_mtimes())
    except Exception:
        return {**NUMBERS_FALLBACK, "source": "снимок по умолчанию"}


def _pc(v: float) -> str:
    return f"{v * 100:.1f}".replace(".", ",") + " процента"


def numbers_chunk() -> dict[str, str]:
    """Раздел базы знаний «Арена метрик и цифры» с подставленными актуальными числами."""
    n = live_numbers()
    return {
        "id": "validation_numbers",
        "paths": "/validation /expertise",
        "keywords": "точность метрики арена бенчмарк цифры p@5 p@10 mrr recall ndcg bm25 резюме раздутые грейд ступень "
                    "атаки оценщик слив проверка валидация доказательства сколько процент",
        "content": (
            f"Экран: Проверка механики (/validation), первый экран — «Арена метрик» (данные на {n['as_of']}, {n['source']}). "
            f"Вкладка «Арена ранжирования»: Драфт против поиска по резюме на мире со скрытой истиной. "
            f"Точность первой пятёрки P@5 — {_pc(n['p5'])}, первой десятки P@10 — {_pc(n['p10'])}, "
            f"MRR — {_pc(n['mrr'])} (подходящий кандидат почти всегда первым), Recall@30 — {_pc(n['recall30'])}. "
            f"Отрыв от полнотекстового поиска BM25 в процентных пунктах: плюс {n['p5_vs_bm25'] * 100:.0f} по P@5 и "
            f"плюс {n['p10_vs_bm25'] * 100:.0f} по P@10. Раздутые резюме в первой десятке: {_pc(n['inflated_top10'])} у Драфта "
            f"против {_pc(n['inflated_top10_bm25'])} у BM25. "
            f"Вкладка «Точность грейда»: в пределах одной ступени — {_pc(n['within1_one_session'])} за одну сессию и "
            f"{_pc(n['within1_retest'])} при повторе; точный грейд вдали от границы — {_pc(n['far_from_cut'])}, без занижения "
            f"заявки — {_pc(n['no_under_claim'])}, при двухэтапном подтверждении — {_pc(n['two_stage'])}. "
            f"Защита оценщика: прошло {n['attacks_passed']} из {n['attacks_n']} атак. "
            f"Демо-пул — {n['demo_candidates']} кандидатов. Это синтетика: проверяется механика, а не люди."
        ),
    }


def retrieve_rag(query: str, current_path: str) -> str:
    """Подбирает знания о текущем экране + наиболее близкие разделы по словам запроса."""
    q_words = set(re.findall(r"[а-яёa-z0-9@]{3,}", (query or "").lower()))
    scored: list[tuple[int, dict[str, str]]] = []
    for ch in [*RAG_CHUNKS, numbers_chunk()]:
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
1. Говори тепло, интеллигентно, энергично и кратко: строго 1–2 предложения за один раз (до 220 знаков), ТОЛЬКО чистым русским текстом для озвучки вслух (без списков, звёздочек, решёток и кавычек). Числа пиши словами по-русски, без символов процента и @ (например, «семьдесят пять и одна десятая процента», «P@5» — «точность первой пятёрки»). Цифры точности бери только из базы знаний ниже.
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
  "jump_to_step": число от 0 до 12 или null (10 — криптопаспорт попытки с QR, 11 — устная защита кода, 12 — Арена метрик на /validation)
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
    # KF4: новые шаги тура (индексы TOUR_STEPS 10–12 — добавлены в конец, прежние номера не сдвинуты)
    if "арен" in t or "метрик" in t or "валидац" in t or "точност" in t or "цифр" in t:
        return 12
    if "паспорт" in t and "фсп" not in t or "qr" in t or "кью ар" in t or "крипто" in t:
        return 10
    if "защит" in t or "устн" in t:
        return 11
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
        f"текущий адрес экрана = {current_path}, шаг маршрута = {step_index + 1} из {TOUR_STEPS_TOTAL}.\n\n"
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
            jmp = d.get("jump_to_step") if isinstance(d.get("jump_to_step"), int) and 0 <= d.get("jump_to_step") < TOUR_STEPS_TOTAL else fallback_jump
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

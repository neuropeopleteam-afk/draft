"""Живой голосовой ИИ-проводник Елена: сценарий обзора, мгновенные ответы, база знаний и голос.

Разговор идёт «как по видеосвязи»: микрофон включается один раз (live_stt.py — потоковое распознавание), на каждый
законченный ход собеседника фронтенд зовёт POST /api/interview/concierge/turn и получает поток NDJSON:

  {"t": "ack", "kind": "instant" | "llm"}        — сразу: будет ли думать модель (фронт ставит короткую связку)
  {"t": "meta", "reply": ..., "action": ..., ...} — решение: что сказать и что сделать на экране
  {"t": "pcm", "b64": ...}                        — голос ответа (PCM s16le 24 кГц моно) по ~200 мс
  {"t": "end", "ms": ...}

Голос — потоковый синтез поставщика через ретранслятор (первый звук ≈ 0,7 с), постоянные фразы (приветствие, реплики
шагов обзора, связки) — из дискового кэша без ожидания (прогрев при первом обращении к /concierge/script).
Знакомство, выбор роли и команды («стоп», «дальше», «повтори», «назад», «покажи тест») — мгновенно, без модели;
вопросы о платформе — быстрая модель через OpenRouter с базой знаний RAG (1–2 предложения, JSON).
Названия внешних сервисов в речи не звучат.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Literal

from app.modules.interview import port as pt

log = logging.getLogger("interview.concierge")

Role = Literal["all", "candidate", "employer", "fsp"]
ROLES = ("all", "candidate", "employer", "fsp")

# ------------------------------------------------------------------ голос

TTS_HOST = "api.elevenlabs.io"
TTS_MODEL = os.environ.get("CONCIERGE_TTS_MODEL", "eleven_turbo_v2_5")
TTS_SPEED = float(os.environ.get("CONCIERGE_TTS_SPEED", "1.06"))
# fmt → (формат поставщика, MIME, частота)
FORMATS: dict[str, tuple[str, str, int]] = {
    "pcm24": ("pcm_24000", "audio/pcm", 24000),
    "pcm": ("pcm_16000", "audio/pcm", 16000),
    "mp3": ("mp3_44100_64", "audio/mpeg", 0),
}


def _cache_dir() -> Path:
    for cand in (os.environ.get("CONCIERGE_TTS_CACHE_DIR"), "/srv/cache/concierge", "/tmp/concierge_tts_cache"):
        if not cand:
            continue
        p = Path(cand)
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".w"
            probe.write_bytes(b"1")
            probe.unlink(missing_ok=True)
            return p
        except OSError:
            continue
    return Path("/tmp")


_CACHE = _cache_dir()


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _voice() -> tuple[str, str]:
    from app.modules.interview.engine.settings import get_interview_settings

    s = get_interview_settings()
    return s.elevenlabs_api_key or "", s.elevenlabs_voice_id or ""


def _key(text: str, fmt: str) -> str:
    _, voice = _voice()
    return hashlib.sha256(f"{TTS_MODEL}|{voice}|{TTS_SPEED}|{fmt}|{_clean(text)}".encode("utf-8")).hexdigest()[:40]


def cache_path(text: str, fmt: str) -> Path:
    return _CACHE / f"{_key(text, fmt)}.{fmt}"


def cached(text: str, fmt: str) -> bytes | None:
    fp = cache_path(text, fmt)
    try:
        if fp.is_file() and fp.stat().st_size > 200:
            return fp.read_bytes()
    except OSError:
        pass
    return None


def _store(text: str, fmt: str, data: bytes) -> None:
    if len(data) < 1000:
        return
    fp = cache_path(text, fmt)
    try:
        tmp = fp.with_suffix(fp.suffix + f".{os.getpid()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(fp)
    except OSError:
        pass


def _trim_head(buf: bytearray, rate: int) -> bytes:
    """Срезать тишину в начале PCM (оставив 40 мс): ответ звучит сразу, без «пустой» паузы поставщика."""
    view = memoryview(buf)
    n = len(buf) // 2
    i = 0
    limit = min(n, int(rate * 0.8))
    while i < limit:
        v = int.from_bytes(view[i * 2:i * 2 + 2], "little", signed=True)
        if abs(v) > 420:
            break
        i += 1
    if i >= limit:
        return bytes(buf)  # тишины больше 0,8 с или звук не найден — отдаём как есть
    start = max(0, i - int(rate * 0.04))
    return bytes(buf[start * 2:])


class TtsError(RuntimeError):
    pass


def synth_stream(text: str, fmt: str = "pcm24") -> Iterator[bytes]:
    """Голос фразы кусками по мере синтеза; постоянные фразы — из кэша. Куски PCM всегда чётной длины."""
    clean = _clean(text)
    if not clean:
        return
    hit = cached(clean, fmt)
    if hit:
        step = 19200
        for i in range(0, len(hit), step):
            yield hit[i:i + step]
        return
    out_fmt, _mime, rate = FORMATS[fmt]
    key, voice = _voice()
    if not key or not voice:
        raise TtsError("tts_not_configured")
    import httpx

    from app.modules.interview.engine.providers import relay

    path = f"/v1/text-to-speech/{voice}/stream?output_format={out_fmt}"
    r = relay.route(TTS_HOST, path, {"xi-api-key": key, "Content-Type": "application/json", "Accept": "*/*"})
    body = {
        "text": clean,
        "model_id": TTS_MODEL,
        "language_code": "ru",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True,
                           "speed": TTS_SPEED},
    }
    whole = bytearray()
    head = bytearray()
    head_done = rate == 0
    tail = b""
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=6.0), verify=r.verify) as c:
            with c.stream("POST", r.url, headers=r.headers, json=body) as resp:
                if resp.status_code >= 400:
                    raise TtsError(f"tts_http_{resp.status_code}")
                for chunk in resp.iter_bytes():
                    if not chunk:
                        continue
                    if not head_done:
                        head.extend(chunk)
                        if len(head) < int(rate * 2 * 0.35):  # копим ~350 мс, чтобы срезать тишину в начале
                            continue
                        data = _trim_head(head, rate)
                        head_done = True
                    else:
                        data = chunk
                    data = tail + data
                    if rate:
                        even = len(data) - len(data) % 2
                        data, tail = data[:even], data[even:]
                    whole.extend(data)
                    for i in range(0, len(data), 9600):
                        yield data[i:i + 9600]
        if not head_done and head:
            data = _trim_head(head, rate)
            data = data[: len(data) - len(data) % 2]
            whole.extend(data)
            for i in range(0, len(data), 9600):
                yield data[i:i + 9600]
    except TtsError:
        raise
    except Exception as e:  # noqa: BLE001 — сеть, ретранслятор
        raise TtsError(type(e).__name__) from e
    log.info("concierge tts %s: %d байт за %d мс", fmt, len(whole), int((time.monotonic() - t0) * 1000))
    _store(clean, fmt, bytes(whole))


def synth_bytes(text: str, fmt: str = "pcm24") -> bytes:
    hit = cached(text, fmt)
    if hit:
        return hit
    return b"".join(synth_stream(text, fmt))


@lru_cache(maxsize=256)
def cached_speak(text: str, fmt: Literal["mp3", "pcm_16000"]) -> tuple[bytes, str]:
    """Совместимость: /concierge/speech (mp3 или pcm 16 кГц) для советника и стенда архитектора."""
    f = "pcm" if fmt == "pcm_16000" else "mp3"
    try:
        data = synth_bytes(text, f)
        if data:
            return data, FORMATS[f][1]
    except TtsError:
        pass
    audio, actual_mime, _usd = pt.get_port().speak(_clean(text), fmt)
    return audio, actual_mime or FORMATS[f][1]


# ------------------------------------------------------------------ сценарий обзора

GREETING = ("Здравствуйте. Я Елена, проводник по Драфту. Как вас зовут и кем вы здесь: кандидатом или работодателем? "
            "Могу показать и весь сайт.")
NUDGE = "Тогда начну обзор всего сайта, а вы перебивайте меня в любой момент."

BRIDGES: dict[str, str] = {
    "candidate": "Открываю кабинет кандидата.",
    "employer": "Переходим в кабинет работодателя.",
    "fsp": "Теперь кабинет Федерации спортивного программирования.",
    "validation": "И напоследок — цифры проверки.",
}

PHRASES: dict[str, str] = {
    "pause": "Хорошо, жду. Скажите «дальше», когда продолжим.",
    "start": "Отлично, начинаем.",
    "goto": "Сейчас покажу.",
    "bye": "Хорошо. Если понадоблюсь, я в правом нижнем углу.",
    "sorry": "Не расслышала. Повторите, пожалуйста.",
    "done_all": "Это главное. Спрашивайте о чём угодно — я слушаю.",
    "done_candidate": "Это главное для кандидата. Спросите о чём угодно или скажите «работодатель» — покажу вторую сторону.",
    "done_employer": "Так работодатель находит подтверждённых специалистов. Спрашивайте или скажите «кандидат» — покажу его кабинет.",
    "done_fsp": "Это кабинет федерации. Спрашивайте, если что-то интересно.",
    "resume_q": "Продолжаю обзор.",
    "hello": "Здравствуйте. Как вас зовут и кем вы здесь: кандидатом или работодателем?",
    "nomic": "Здравствуйте. Я Елена, проводник по Драфту. Микрофон недоступен, поэтому просто проведу вас по сайту.",
}

FILLERS = ("Секунду.", "Так, сейчас.", "Хороший вопрос.", "Сейчас расскажу.")


_U = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_U_F = {1: "одна", 2: "две"}
_TEEN = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать",
         "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUND = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
_U_G = ["нуля", "одного", "двух", "трёх", "четырёх", "пяти", "шести", "семи", "восьми", "девяти"]
_TEEN_G = ["десяти", "одиннадцати", "двенадцати", "тринадцати", "четырнадцати", "пятнадцати", "шестнадцати", "семнадцати",
           "восемнадцати", "девятнадцати"]
_TENS_G = ["", "", "двадцати", "тридцати", "сорока", "пятидесяти", "шестидесяти", "семидесяти", "восьмидесяти", "девяноста"]
_HUND_G = ["", "ста", "двухсот", "трёхсот", "четырёхсот", "пятисот", "шестисот", "семисот", "восьмисот", "девятисот"]


def num_words(n: int, *, gen: bool = False, fem: bool = False) -> str:
    """Число 0…999 словами (именительный или родительный падеж; одна/две — для женского рода)."""
    n = max(0, min(999, int(n)))
    if n == 0:
        return _U_G[0] if gen else _U[0]
    parts: list[str] = []
    h, r = divmod(n, 100)
    if h:
        parts.append((_HUND_G if gen else _HUND)[h])
    if 10 <= r < 20:
        parts.append((_TEEN_G if gen else _TEEN)[r - 10])
    else:
        tn, u = divmod(r, 10)
        if tn:
            parts.append((_TENS_G if gen else _TENS)[tn])
        if u:
            if gen:
                parts.append("одной" if fem and u == 1 else _U_G[u])
            else:
                parts.append(_U_F.get(u, _U[u]) if fem else _U[u])
    return " ".join(parts)


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def _arena_speech() -> str:
    n = live_numbers()
    pp = int(round(float(n.get("p5_vs_bm25", 0.31)) * 100))
    within = round(float(n.get("within1_one_session", 0.9936)) * 100, 1)
    attacks = int(n.get("attacks_n", 116))
    passed = int(n.get("attacks_passed", 0))
    w_int, w_frac = int(within), int(round((within - int(within)) * 10))
    if w_frac:
        within_txt = f"{num_words(w_int)} и {num_words(w_frac, fem=True)} {plural(w_frac, 'десятая', 'десятых', 'десятых')} процента"
    else:
        within_txt = f"{num_words(w_int)} {plural(w_int, 'процент', 'процента', 'процентов')}"
    tail = "ни одна не прошла" if passed == 0 else f"прошли {num_words(passed, fem=True)}"
    return (
        f"И главное — цифры. В первой пятёрке Драфта подходящих кандидатов на {num_words(pp)} "
        f"{plural(pp, 'процентный пункт', 'процентных пункта', 'процентных пунктов')} больше, чем у поиска по резюме, "
        f"а раздутые резюме почти не попадают в первую десятку. Грейд в пределах одной ступени — {within_txt}, "
        f"а из {num_words(attacks, gen=True)} атак на оценщика {tail}."
    )


STEP_SPEECH: dict[str, str] = {
    "cand-overview": (
        "Это кабинет кандидата. Наверху — переключатель ролей, в центре — маршрут из четырёх шагов: стек, тест на грейд, "
        "устная защита и приглашения. Нажимаю второй шаг."
    ),
    "cand-assessment": (
        "Здесь выбирают грейд, который хотите подтвердить. Отмечаю Senior — прямо под карточками галочка согласия и кнопка "
        "«Начать тест». Задания подстраиваются под ваши ответы, поэтому тест короче обычного."
    ),
    "cand-feedback": (
        "Это карта навыков. Шкала показывает ваш уровень и точность оценки, ниже — маршрут роста с кнопками и сравнение "
        "со спросом на рынке."
    ),
    "cand-passport": (
        "Каждая попытка теста подписана платформой. Работодатель проверяет её по кью-ар коду за пару секунд — без звонков."
    ),
    "cand-defense": (
        "А это устная защита: три минуты разговора с ИИ-интервьюером по вашим же решениям. Скопированный ответ так не защитить."
    ),
    "cand-invitations": (
        "В приглашениях компания сразу называет зарплатную вилку, а контакты открываются, только когда вы примете предложение."
    ),
    "emp-needs": (
        "Это кабинет работодателя. Опишите, кого ищете, своими словами — я подставлю пример. Кнопка «Разобрать требования» "
        "выделит стек и уберёт дискриминационные формулировки."
    ),
    "emp-compare": (
        "На сравнении кандидатов сверху — формула ранжирования: тест, обязательный стек, достижения ФСП и задания. "
        "Ниже — таблица по каждому требованию и кнопка «Пригласить» с вилкой."
    ),
    "fsp-cabinet": (
        "Кабинет Федерации спортивного программирования: спрос работодателей, влияние побед на приглашения и зарплаты, "
        "отборочные кубки под вакансии. Открываю эффект соревнований."
    ),
}

STEP_IDS = (*STEP_SPEECH.keys(), "val-arena")


def script() -> dict:
    steps = dict(STEP_SPEECH)
    steps["val-arena"] = _arena_speech()
    return {"greeting": GREETING, "nudge": NUDGE, "bridges": BRIDGES, "phrases": PHRASES, "fillers": list(FILLERS),
            "steps": steps, "format": "pcm24", "rate": 24000}


def script_texts() -> list[str]:
    sc = script()
    return [sc["greeting"], sc["nudge"], *sc["bridges"].values(), *sc["phrases"].values(), *sc["fillers"], *sc["steps"].values()]


_warm_lock = threading.Lock()
_warm_started = False


def warm_async() -> None:
    """Однажды на процесс: озвучить постоянные фразы сценария в кэш (несколько секунд в фоне)."""
    global _warm_started
    with _warm_lock:
        if _warm_started:
            return
        _warm_started = True

    def run() -> None:
        lock = _CACHE / ".warm.lock"
        try:
            if lock.exists() and time.time() - lock.stat().st_mtime < 120:
                return  # другой воркер уже греет
            lock.write_text(str(os.getpid()))
        except OSError:
            pass
        n = 0
        for text in script_texts():
            if cached(text, "pcm24"):
                continue
            try:
                synth_bytes(text, "pcm24")
                n += 1
            except TtsError as e:
                log.warning("concierge warm: %s", e)
                break
        log.info("concierge warm: озвучено %d новых фраз", n)

    threading.Thread(target=run, name="concierge-warm", daemon=True).start()


# ------------------------------------------------------------------ база знаний (RAG)

RAG_CHUNKS: list[dict[str, str]] = [
    {
        "id": "landing",
        "paths": "/",
        "keywords": "главная витрина закон драфт почему резюме обратный найм старт вход регистрация",
        "content": (
            "Главная страница: обратный найм — работодатель сам находит подтверждённого специалиста и сразу называет "
            "зарплатную вилку. Кандидат один раз подтверждает уровень адаптивным тестом и получает категорию "
            "«направление · грейд». Блок «4 закона Драфта» — с вкладками для работодателя, кандидата и Федерации "
            "спортивного программирования."
        ),
    },
    {
        "id": "candidate_overview",
        "paths": "/candidate",
        "keywords": "кабинет кандидата обзор дорожная карта шаг маршрут роль выйти",
        "content": (
            "Кабинет кандидата (/candidate): сверху переключатель ролей и кнопка «Выйти»; в центре маршрут из 4 шагов: "
            "1 — направление и стек (опрос), 2 — адаптивный тест на грейд, 3 — устная защита кода с ИИ-интервьюером "
            "(3 минуты голосом), 4 — карта роста и приглашения с зарплатой."
        ),
    },
    {
        "id": "candidate_assessment",
        "paths": "/candidate/assessment /candidate/express",
        "keywords": "тест грейд опрос стажёр junior middle senior lead principal согласие галочка начать экспресс полный античит адаптивный",
        "content": (
            "Опрос и тест (/candidate/assessment): 6 карточек грейда (Стажёр, Junior, Middle, Senior, Lead, Principal); "
            "под ними галочка согласия на проверку самостоятельности и кнопка «Начать тест». Тест адаптивный (психометрия "
            "IRT): каждое следующее задание выбирается под уровень по прошлым ответам, банк — 403 семейства и 8 060 "
            "вариантов. Полный режим — до 80 минут, экспресс-калибровка — около 5 минут. Наказаний автоматически нет: "
            "сигналы честности видит работодатель."
        ),
    },
    {
        "id": "candidate_feedback",
        "paths": "/candidate/feedback /candidate/category",
        "keywords": "карта навыков рост шкала irt тета психометрия пробелы рынок hh вакансии маршрут задачи погрешность",
        "content": (
            "Карта навыков и рост (/candidate/feedback): шкала уровня с погрешностью оценки и зонами грейдов, "
            "«Маршрут роста» с кнопками действий (добавить навык в стек, задачи с автопроверкой, тест на грейд), "
            "сравнение со спросом рынка по открытым вакансиям hh.ru."
        ),
    },
    {
        "id": "candidate_attempts",
        "paths": "/candidate/attempts",
        "keywords": "паспорт попытка подпись qr кью ар честность защита устная интервьюер",
        "content": (
            "Попытки и устная защита (/candidate/attempts): каждая попытка теста подписана электронной подписью "
            "платформы; работодатель проверяет паспорт по QR-коду без входа. Устная защита — 3 минуты разговора с "
            "ИИ-интервьюером по своим решениям: грейд не меняется, подтверждается самостоятельность."
        ),
    },
    {
        "id": "candidate_invitations",
        "paths": "/candidate/invitations /candidate/fsp /candidate/assignments",
        "keywords": "приглашения оффер вилка зарплата принять отклонить контакты паспорт фсп достижения кубок задания",
        "content": (
            "Приглашения (/candidate/invitations): компания обязана сразу указать вилку «от — до» в рублях; кандидат "
            "принимает (только тогда открываются контакты), отклоняет или предлагает свою вилку. Паспорт ФСП — "
            "подтверждённые спортивные достижения из реестра Федерации спортивного программирования."
        ),
    },
    {
        "id": "employer_needs",
        "paths": "/employer/needs /employer",
        "keywords": "работодатель компания потребность вакансия текст разобрать ст 64 тк рф подборка кандидаты формула ранжирование",
        "content": (
            "Кабинет работодателя (/employer/needs): описание вакансии своими словами, голосом или файлом, кнопка "
            "«Подставить пример», затем «Разобрать требования» — выделяется обязательный и желательный стек с цитатами, "
            "зарплата сверяется с рынком, дискриминационные формулировки (ст. 64 ТК РФ) убираются. Подборка ранжирует "
            "кандидатов: 45 % — тест, 35 % — обязательный стек, 10 % — реестр ФСП, 5 % — задания, 5 % — желательный стек."
        ),
    },
    {
        "id": "employer_compare",
        "paths": "/employer/compare /employer/needs",
        "keywords": "сравнение сравнить советник руководителя таблица матрица лидер пригласить",
        "content": (
            "Сравнение кандидатов: полоса формулы ранжирования, ИИ-советник руководителя (доклад: кто лидер по тесту и "
            "паспорту ФСП, о чём спросить на финальном созвоне), таблица по каждому требованию и кнопки «Пригласить» и "
            "«Задание всем»."
        ),
    },
    {
        "id": "fsp_cabinet",
        "paths": "/fsp",
        "keywords": "фсп федерация спортивного программирования аналитика спрос регионы эффект соревнований зарплаты кубки",
        "content": (
            "Кабинет ФСП (/fsp): обезличенная аналитика — спрос работодателей по категориям и навыкам, эффект "
            "соревнований (как достижения ФСП влияют на приглашения), зарплаты из офферов против рынка, воронки и "
            "кубки работодателей."
        ),
    },
]

# ------------------------------------------------------------------ цифры (docs/NUMBERS.json → бенчмарк → снимок)

_HERE = Path(__file__).resolve()
_BENCH_JSON = _HERE.parents[1] / "validation" / "data" / "matching_bench.json"
_ACCURACY_JSON = _HERE.parents[1] / "validation" / "data" / "accuracy_views.json"


def _numbers_paths() -> list[Path]:
    env = os.environ.get("CONCIERGE_NUMBERS_PATH")
    out = [Path(env)] if env else []
    for up in (4, 3):
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
    n = live_numbers()
    return {
        "id": "validation_numbers",
        "paths": "/validation /expertise",
        "keywords": "точность метрики арена бенчмарк цифры bm25 резюме раздутые грейд ступень атаки оценщик проверка "
                    "валидация доказательства сколько процент",
        "content": (
            f"Проверка механики (/validation), «Арена метрик» (данные на {n['as_of']}). Драфт против поиска по резюме на "
            f"мире со скрытой истиной: точность первой пятёрки — {_pc(n['p5'])}, первой десятки — {_pc(n['p10'])}; "
            f"отрыв от полнотекстового поиска — плюс {n['p5_vs_bm25'] * 100:.0f} процентных пунктов в пятёрке; раздутые "
            f"резюме в десятке: {_pc(n['inflated_top10'])} у Драфта против {_pc(n['inflated_top10_bm25'])}. Грейд в "
            f"пределах одной ступени — {_pc(n['within1_one_session'])} за одну сессию; защита оценщика: прошло "
            f"{n['attacks_passed']} из {n['attacks_n']} атак. Это синтетика: проверяется механика, а не люди."
        ),
    }


def retrieve_rag(query: str, current_path: str) -> str:
    q_words = set(re.findall(r"[а-яёa-z0-9@]{3,}", (query or "").lower()))
    scored: list[tuple[int, dict[str, str]]] = []
    for ch in [*RAG_CHUNKS, numbers_chunk()]:
        score = 0
        paths = ch["paths"].split()
        if any(current_path == p or (p != "/" and current_path.startswith(p)) for p in paths):
            score += 30
        kw = ch["keywords"] + " " + ch["content"].lower()
        for w in q_words:
            if w in kw:
                score += 10
        scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [ch["content"] for sc, ch in scored[:3] if sc > 0] or [RAG_CHUNKS[0]["content"]]
    return "\n\n".join(picked)


# ------------------------------------------------------------------ понимание реплики

_NAME_RE = re.compile(
    r"(?:меня\s+зовут|мо[её]\s+имя|зовите\s+меня|зови\s+меня|обращайтесь\s+ко\s+мне|я\s+[-—–])\s*([А-ЯЁа-яё]{2,20})", re.I)
_SIMPLE_NAME_RE = re.compile(
    r"^\s*(?:(?:привет|здравствуйте|здрасте|добрый\s+(?:день|вечер)|доброе\s+утро)[\s,.]*)?(?:это\s+|я\s+)?([А-ЯЁа-яё]{2,18})"
    r"(?:[\s,.]+(?:я\b|мне\b|кандидат|работодатель|покажи|хочу|интерес|из\b|компан).*)?[\s.!?]*$", re.I)
_STOP_NAMES = {
    "привет", "здравствуйте", "здрасте", "добрый", "пока", "покажи", "покажите", "расскажи", "расскажите", "кандидат", "работодатель",
    "компания", "федерация", "эксперт", "жюри", "давай", "давайте", "хочу", "кто", "что", "как", "где", "зачем", "почему",
    "дальше", "стоп", "пауза", "весь", "всё", "все", "сайт", "просто", "ничего", "алло", "начинай", "начинайте", "начнем",
    "начнём", "поехали", "открой", "перейди", "тест", "вакансии", "да", "нет", "ага", "угу", "хорошо", "ладно", "окей",
    "понятно", "спасибо", "конечно", "подожди", "погоди", "повтори", "назад", "продолжай", "продолжим", "елена", "лена",
    "слушай", "слушаю", "можно", "интересно", "здорово", "отлично", "супер", "классно", "ясно", "так", "вот", "ну",
    "работаю", "ищу", "нанимаю", "эйчар", "рекрутер", "разработчик", "программист", "студент", "директор", "руководитель",
    "мы", "вы", "он", "она", "они", "мне", "нас", "наш", "наша", "это", "тут", "здесь", "сейчас", "сегодня", "покажешь",
    "проведи", "проведите", "начни", "начните", "можешь", "можете", "умеешь", "слышишь", "слышите", "привет",
}


def extract_name(text: str, current_name: str | None = None) -> str | None:
    if current_name:
        return current_name
    t = (text or "").strip()
    for rx in (_NAME_RE, _SIMPLE_NAME_RE):
        m = rx.search(t) if rx is _NAME_RE else rx.match(t)
        if m:
            cand = m.group(1).strip()
            if cand.lower() not in _STOP_NAMES and not cand.lower().startswith(("кандидат", "работодат")):
                return cand[:1].upper() + cand[1:].lower()
    return None


def detect_role(text: str) -> Role | None:
    t = (text or "").lower()
    if re.search(r"работодат|компани|нанима|эйчар|\bhr\b|рекрут|ищу (?:сотрудник|разработчик|специалист|людей)|"
                 r"директор|руководител|тимлид|найм", t):
        return "employer"
    if re.search(r"\bфсп\b|федерац|аналитик федерац", t):
        return "fsp"
    if re.search(r"кандидат|соискат|разработчик|программист|ищу работу|работу ищу|специалист|инженер|студент|"
                 r"джун|мидл|сеньор|синьор", t):
        return "candidate"
    if re.search(r"весь сайт|всё покаж|все покаж|покажи(?:те)? всё|покажи(?:те)? все|целиком|обзор|экскурс|жюри|"
                 r"эксперт|с самого начала|всю платформ|полностью", t):
        return "all"
    return None


_GOTO: list[tuple[str, str]] = [
    (r"арен|метрик|точност|бенчмарк|валидац|цифр", "val-arena"),
    (r"паспорт(?! фсп)|\bqr\b|кью.?ар|подпис", "cand-passport"),
    (r"защит|устн|интервьюер", "cand-defense"),
    (r"тест|грейд|опрос", "cand-assessment"),
    (r"карт\w* навык|навык|шкал|рост", "cand-feedback"),
    (r"приглаш|оффер|вилк", "cand-invitations"),
    (r"сравн|советник", "emp-compare"),
    (r"потребност|ваканси|разбор требован", "emp-needs"),
    (r"кабинет фсп|кабинет федерац|аналитик", "fsp-cabinet"),
]


def detect_goto(text: str) -> str | None:
    t = (text or "").lower()
    if not re.search(r"покажи|покажите|открой|откройте|перейди|перейдите|где|давай|хочу|можно|а как|расскажи", t):
        return None
    for rx, sid in _GOTO:
        if re.search(rx, t):
            return sid
    return None


def _words(text: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", (text or "").lower())


CMD_PAUSE = re.compile(r"^(?:ой\s+)?(?:стоп|пауза|подожди(?:те)?|погоди(?:те)?|секунду|минуту|остановись|остановитесь|"
                       r"замолчи|тише|хватит пока|не так быстро|постой(?:те)?)\b")
CMD_RESUME = re.compile(r"^(?:ну\s+|да\s+|давай(?:те)?\s+)?(?:дальше|продолжа\w*|продолжим|поехали|вперёд|вперед|следующ\w*|"
                        r"давай(?:те)? дальше|идём дальше|идем дальше|едем дальше)\b")
CMD_REPEAT = re.compile(r"\b(?:повтори(?:те)?|ещё раз|еще раз|не понял\w*|не расслышал\w*|что ты сказала|что вы сказали)\b")
CMD_BACK = re.compile(r"^(?:назад|вернись|вернитесь|верни(?:те)?|предыдущ\w*|обратно)\b")
CMD_BYE = re.compile(r"\b(?:до свидания|пока пока|закончим|заканчива\w*|заверш\w*|выключ\w*|закрой\w*|спасибо[, ]+всё|"
                     r"всё[, ]+спасибо|все[, ]+спасибо|больше не надо|на этом вс[её]|хватит на сегодня)\b")
HELLO = re.compile(r"^(?:привет\w*|здравствуй\w*|здрасте|добрый\s+(?:день|вечер)|доброе\s+утро|доброго\s+дня|"
                   r"хай|алло|ал[её]|салют|приветствую)\b")
YES = re.compile(r"^(?:да|ага|угу|конечно|давай(?:те)?|хорошо|окей|ок|ладно|можно)"
                 r"(?:\s+(?:да|давай(?:те)?|конечно|покажи(?:те)?|можно|пожалуйста|хорошо|интересно))*[\s,.!]*$")
BYE_SHORT = re.compile(r"^(?:ну\s+)?(?:пока|до встречи|всего доброго|всего хорошего)(?:\s+пока)?$")
QUESTION = re.compile(r"\?|^(?:а\s+)?(?:почему|зачем|сколько|откуда|какой|какая|какие|каким|как|что|чем|кто|где|когда|"
                      r"можно ли|правда|расскажи|расскажите|объясни|объясните)\b")


def _norm(text: str) -> str:
    return " ".join(_words(text))


def classify(message: str, *, touring: bool, paused: bool) -> dict | None:
    """Мгновенное решение без модели или None (нужна модель)."""
    t = _norm(message)
    if not t:
        return None
    n = len(t.split())
    raw = (message or "").strip().lower()
    if (n <= 6 and CMD_BYE.search(t) and not QUESTION.search(raw)) or BYE_SHORT.search(t):
        return {"action": "end", "phrase": "bye"}
    if n <= 5 and CMD_PAUSE.search(t):
        return {"action": "pause", "phrase": "pause"}
    if n <= 5 and CMD_BACK.search(t):
        return {"action": "prev"}
    if n <= 6 and CMD_REPEAT.search(t):
        return {"action": "repeat"}
    if n <= 5 and CMD_RESUME.search(t):
        return {"action": "resume"}
    if (paused or touring) and n <= 3 and YES.search(t):
        return {"action": "resume"}
    return None


def _start_reply(name: str | None, role: Role, first_time: bool) -> str:
    who = {"candidate": "кабинет кандидата", "employer": "кабинет работодателя",
           "fsp": "кабинет Федерации", "all": "весь сайт по шагам"}[role]
    if name and first_time:
        return f"Приятно познакомиться, {name}. Показываю {who}."
    if name:
        return f"{name}, показываю {who}."
    return f"Отлично, показываю {who}."


SYSTEM_PROMPT = """Ты — Елена, живой голосовой проводник платформы обратного найма «Драфт». Твои слова звучат голосом
видеоаватара, человек слышит тебя, текста на экране нет.

Правила:
1. Отвечай тепло, живо и очень кратко: 1–2 коротких предложения (до 200 знаков), только чистый русский текст для
   произнесения вслух — без списков, звёздочек, кавычек-ёлочек, эмодзи и символов процента или @ (говори «процентов»).
2. Отвечай строго по базе знаний ниже; если ответа там нет — честно скажи, что покажешь это на экране, и предложи шаг.
3. Не называй внешние сервисы и технологии (ElevenLabs, Anam, Deepgram, OpenRouter, WebRTC и подобные).
4. Если человек назвал имя — верни его в user_name. Если выбрал роль — action "start_tour" и role.
   Если просит показать конкретный экран — action "goto" и step. На вопрос — action "answer".
   Если хочет закончить — action "end". Если просит подождать — action "pause".

Шаги для step: cand-overview (кабинет кандидата), cand-assessment (тест и грейд), cand-feedback (карта навыков),
cand-passport (подписанный паспорт попытки, QR), cand-defense (устная защита), cand-invitations (приглашения с вилкой),
emp-needs (вакансия и разбор требований), emp-compare (сравнение кандидатов и формула), fsp-cabinet (кабинет ФСП),
val-arena (цифры точности).

Ответ — строго JSON:
{"reply": "...", "action": "answer"|"start_tour"|"goto"|"pause"|"end", "role": "all"|"candidate"|"employer"|"fsp"|null,
 "step": "<id шага>"|null, "user_name": "Имя"|null}"""

LLM_MODELS = [m.strip() for m in os.environ.get(
    "CONCIERGE_LLM_MODELS", "openrouter=google/gemini-2.5-flash|openrouter=google/gemini-2.5-flash-lite").split("|") if m.strip()]


def _clean_reply(text: str) -> str:
    t = re.sub(r"[*#`_~«»\"]+", "", str(text or ""))
    t = t.replace("%", " процентов").replace("@", " ")
    t = re.sub(r"!", ".", t)
    return " ".join(t.split()).strip()[:320]


def _llm(message: str, *, user_name: str | None, role: str | None, current_path: str, step_id: str | None,
         history: list[dict] | None) -> dict | None:
    from app.modules.llm import client as llm

    rag = retrieve_rag(message, current_path)
    state = (f"Состояние: имя собеседника — {user_name or 'неизвестно'}; роль — {role or 'не выбрана'}; экран — "
             f"{current_path}; шаг обзора — {step_id or 'нет'}.\n\nБаза знаний:\n{rag}")
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + state}]
    for h in (history or [])[-6:]:
        w = "assistant" if h.get("who") == "elena" else "user"
        c = str(h.get("text") or "").strip()
        if c:
            msgs.append({"role": w, "content": c[:400]})
    msgs.append({"role": "user", "content": message.strip()[:600]})
    deadline = time.monotonic() + 6.0
    for model in LLM_MODELS:
        left = deadline - time.monotonic()
        if left < 1.0:
            break
        try:
            res = llm.chat(msgs, temperature=0.3, max_tokens=180, want_json=True, model=model, timeout_s=min(4.5, left))
        except Exception as e:  # noqa: BLE001
            log.warning("concierge llm %s: %s", model, type(e).__name__)
            continue
        if res.ok and isinstance(res.data, dict) and isinstance(res.data.get("reply"), str) and res.data["reply"].strip():
            d = dict(res.data)
            d["_model"] = res.model
            return d
    return None


def turn(message: str, *, user_name: str | None = None, role: str | None = None, current_path: str = "/",
         step_id: str | None = None, touring: bool = False, paused: bool = False, history: list[dict] | None = None,
         on_ack=None) -> dict:
    """Решение по законченному ходу собеседника.

    Возвращает {reply, phrase, action, role, step, user_name, kind}. phrase — ключ постоянной фразы из кэша (если
    reply пустой). action: ask_role | start_tour | goto | answer | pause | resume | repeat | prev | end | none.
    """
    msg = (message or "").strip()
    name_now = extract_name(msg, None) if not user_name else None
    name = user_name or name_now
    first_time = bool(name_now)
    cur_role = role if role in ROLES else None

    def ack(kind: str) -> None:
        if on_ack:
            on_ack(kind)

    base = {"user_name": name, "role": cur_role, "step": None, "reply": "", "phrase": None}
    quick = classify(msg, touring=touring, paused=paused)
    if quick:
        ack("instant")
        out = {**base, "kind": "instant", "action": quick["action"]}
        if quick.get("phrase"):
            out["phrase"] = quick["phrase"]
        return out

    det = detect_role(msg)
    goto = detect_goto(msg)
    is_q = bool(QUESTION.search(msg.lower())) and len(_words(msg)) > 2
    if det and not is_q:
        ack("instant")
        return {**base, "kind": "instant", "action": "start_tour", "role": det, "reply": _start_reply(name, det, first_time)}
    if goto and not is_q:
        ack("instant")
        return {**base, "kind": "instant", "action": "goto", "step": goto, "phrase": "goto"}
    if not det and not name_now and not is_q and len(_words(msg)) <= 3 and HELLO.search(_norm(msg)):
        ack("instant")
        return {**base, "kind": "instant", "action": "ask_role", "phrase": "hello"}
    if not det and not touring and not paused and len(_words(msg)) <= 3 and YES.search(_norm(msg)):
        r = cur_role or "all"
        ack("instant")
        return {**base, "kind": "instant", "action": "start_tour", "role": r, "reply": _start_reply(name, r, False)}
    if name_now and not is_q and len(_words(msg)) <= 5:
        ack("instant")
        return {**base, "kind": "instant", "action": "ask_role",
                "reply": f"Очень приятно, {name}. Кем вы здесь — кандидатом или работодателем? Или показать весь сайт?"}

    ack("llm")
    d = _llm(msg, user_name=name, role=cur_role, current_path=current_path, step_id=step_id, history=history)
    if not d:
        if goto:
            return {**base, "kind": "fallback", "action": "goto", "step": goto, "phrase": "goto"}
        return {**base, "kind": "fallback", "action": "answer",
                "reply": "Об этом лучше расскажу на экране. Давайте продолжим обзор, а вы перебивайте, если что-то интересно."}
    reply = _clean_reply(d.get("reply", ""))
    action = d.get("action") if d.get("action") in ("answer", "start_tour", "goto", "pause", "end") else "answer"
    llm_role = d.get("role") if d.get("role") in ROLES else None
    step = d.get("step") if d.get("step") in STEP_IDS else None
    llm_name = d.get("user_name") if isinstance(d.get("user_name"), str) and 2 <= len(d["user_name"].strip()) <= 20 else None
    if action == "goto" and not step:
        action = "answer"
    if action == "start_tour" and not (llm_role or cur_role):
        action = "answer"
    return {
        "user_name": name or (llm_name.strip().capitalize() if llm_name else None),
        "role": llm_role or cur_role,
        "step": step,
        "reply": reply,
        "phrase": None,
        "action": action,
        "kind": "llm",
        "model": d.get("_model"),
    }


def turn_stream(message: str, **kw) -> Iterator[bytes]:
    """NDJSON: ack → meta → pcm… → end. Любой сбой голоса — {"t": "voice_error"}, фронт скажет текст своим откатом."""
    import queue

    t0 = time.monotonic()
    q: queue.Queue = queue.Queue()
    box: dict = {}

    def work() -> None:
        try:
            box["res"] = turn(message, on_ack=lambda k: q.put(("ack", k)), **kw)
        except Exception as e:  # noqa: BLE001
            log.warning("concierge turn: %s", type(e).__name__)
        finally:
            q.put(("done", None))

    threading.Thread(target=work, name="concierge-turn", daemon=True).start()
    acked = False
    while True:
        kind, v = q.get()
        if kind == "ack" and not acked:
            acked = True
            yield (json.dumps({"t": "ack", "kind": v}) + "\n").encode()
        elif kind == "done":
            break
    res = box.get("res") or {"user_name": kw.get("user_name"), "role": kw.get("role"), "step": None, "kind": "fallback",
                             "action": "answer", "phrase": "sorry", "reply": ""}
    if not acked:
        yield (json.dumps({"t": "ack", "kind": res.get("kind", "instant")}) + "\n").encode()
    text = res.get("reply") or (PHRASES.get(res["phrase"]) if res.get("phrase") else "")
    meta = {"t": "meta", **{k: v for k, v in res.items() if k != "model"}, "text": text, "ms": int((time.monotonic() - t0) * 1000)}
    yield (json.dumps(meta, ensure_ascii=False) + "\n").encode()
    if text:
        try:
            for chunk in synth_stream(text, "pcm24"):
                yield (json.dumps({"t": "pcm", "b64": base64.b64encode(chunk).decode()}) + "\n").encode()
        except TtsError as e:
            yield (json.dumps({"t": "voice_error", "v": str(e)}) + "\n").encode()
    yield (json.dumps({"t": "end", "ms": int((time.monotonic() - t0) * 1000)}) + "\n").encode()
    log.info("concierge turn: %s/%s за %d мс", res.get("kind"), res.get("action"), int((time.monotonic() - t0) * 1000))


# ------------------------------------------------------------------ совместимость: /concierge/chat (старый фронт)

def reply_chat(message: str, *, user_name: str | None = None, user_role: str | None = None, current_path: str = "/",
               step_index: int = 0, history: list[dict] | None = None) -> dict:
    res = turn(message, user_name=user_name, role=user_role, current_path=current_path, history=history)
    text = res.get("reply") or (PHRASES.get(res["phrase"]) if res.get("phrase") else "") or PHRASES["start"]
    return {
        "reply": text,
        "user_name": res.get("user_name"),
        "detected_role": res.get("role") or "all",
        "start_tour": res.get("action") in ("start_tour", "goto", "resume"),
        "jump_to_step": None,
    }

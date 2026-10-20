"""Живой голосовой ИИ-проводник Настя: сценарий обзора, мгновенные ответы, база знаний и голос.

Разговор идёт «как по видеосвязи», полудуплексом: пока Настя думает или говорит, микрофон закрыт (в распознавание идёт
тишина), открывается через ~0,45 с после конца её фразы — так нет эха, фантомных реплик и перебивания. На каждый
законченный ход собеседника фронтенд зовёт POST /api/interview/concierge/turn и получает поток NDJSON:

  {"t": "ack", "kind": "instant" | "llm"}        — сразу: будет ли думать модель (фронт ставит короткую связку)
  {"t": "meta", "reply": ..., "action": ..., ...} — решение: что сказать и что сделать на экране
  {"t": "pcm", "b64": ...}                        — голос ответа (PCM s16le 24 кГц моно) по ~200 мс
  {"t": "end", "ms": ...}

Голос — потоковый синтез поставщика через ретранслятор (первый звук ≈ 0,7 с), постоянные фразы (приветствие, реплики
шагов обзора, связки) — из дискового кэша без ожидания (прогрев при первом обращении к /concierge/script).
Знакомство, выбор роли и команды («стоп», «дальше», «повтори», «назад», «покажи тест») — мгновенно, без модели;
вопросы о платформе — сильная модель с базой знаний (concierge_kb.md, поиск — concierge_rag.py, память разговора,
стенограммы и фоновый наставник — concierge_brain.py).
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
TTS_SPEED = float(os.environ.get("CONCIERGE_TTS_SPEED", "1.0"))
# Лицо Насти (живой аватар). Экспериментальная «манера» (customStylePrompt) по опыту соседних живых стендов портит
# движение губ, поэтому по умолчанию выключена; выразительность низкая, как у работающих стендов (0,09–0,35):
# лицо спокойное, без лишней мимики, губы следуют речи. Всё настраивается переменными окружения.
ANAM_STYLE = os.environ.get("CONCIERGE_ANAM_STYLE", "").strip()
ANAM_EXPRESSIVITY = float(os.environ.get("CONCIERGE_ANAM_EXPRESSIVITY", "0.2"))
# Своё лицо Насти-проводника: портрет со спокойным лицом и закрытым ртом (исходник интервьюера улыбается во весь рот —
# улыбка исходного кадра манерой не гасится). Создан 20.10.2026 через POST /v1/avatars (one-shot, cara-4);
# происхождение — frontend/public/avatar/PROVENANCE.md. Пусто — общий аватар интервьюера (ANAM_AVATAR_ID).
ANAM_AVATAR_ID = os.environ.get("CONCIERGE_ANAM_AVATAR_ID", "d7d4dd15-e996-4595-ad73-7b77b22e53ec").strip()
# Потолок одного разговора в минутах: по его истечении Настя прощается и закрывается (стенд открыт всем, минуты платные)
MAX_MINUTES = float(os.environ.get("CONCIERGE_MAX_MINUTES", "9"))


def anam_director_notes() -> dict:
    d: dict = {"expressivity": max(0.0, min(1.0, ANAM_EXPRESSIVITY))}
    if ANAM_STYLE:
        d["customStylePrompt"] = ANAM_STYLE[:400]
    return d
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
#
# Обзор — шаги (экраны), у каждого шага несколько коротких реплик («битов»). Каждая реплика — про один блок экрана:
# фронт подсвечивает блок (или подводит курсор и нажимает кнопку) ровно на время этой реплики. Порядок реплик здесь
# и порядок блоков в frontend/src/components/elena/steps.ts совпадают — меняются вместе.

GREETING = "Здравствуйте. Я Настя, ИИ-проводник по «Драфту». Как к вам обращаться?"
GREETING_BACK = "{name}, здравствуйте. Рада снова вас видеть. Показать весь сайт или что-то конкретное?"
NUDGE = "Познакомимся по ходу. Начну с обзора всего сайта. Между экранами я делаю паузу — в ней можно спросить или сказать «стоп»."
NUDGE_ROLE = "Тогда начну со всего сайта. Между экранами я делаю паузу — в ней можно спросить или сказать «стоп»."

# Связки кабинетов: first — обзор начинается с этого кабинета, next — переход из другого кабинета;
# first_named — с именем собеседника ({name})
BRIDGES: dict[str, dict[str, str]] = {
    "home": {"first": "", "next": ""},
    "candidate": {"first": "Начнём со стороны кандидата.", "first_named": "{name}, начнём со стороны кандидата.",
                  "next": "Теперь сторона кандидата."},
    "employer": {"first": "", "next": "Теперь посмотрим глазами работодателя."},
    "fsp": {"first": "", "next": "Теперь кабинет Федерации спортивного программирования."},
    "public": {"first": "", "next": "И напоследок две вещи для технического жюри."},
}

PHRASES: dict[str, str] = {
    "pause": "Хорошо, жду. Скажите «дальше», когда продолжим.",
    "goto": "Сейчас покажу.",
    "bye": "Хорошо. Если понадоблюсь — я в правом нижнем углу.",
    "idle_bye": "Я буду в правом нижнем углу. Нажмите на меня, когда понадоблюсь.",
    "time_up": "На этом моё время с вами заканчивается. Спасибо за разговор. Если понадоблюсь — нажмите на меня снова.",
    "resume_tour": "Продолжаю.",
    "back_tour": "Возвращаюсь к обзору.",
    "sorry": "Не расслышала. Повторите, пожалуйста.",
    "back_to_tour": "Вернёмся к обзору?",
    # между разделами обзора — спросить, есть ли вопросы, и ждать ответа
    "checkin_candidate": "С кандидатом всё. Есть вопросы по этой части?",
    "checkin_employer": "Это была сторона работодателя. Есть вопросы?",
    "checkin_fsp": "Это кабинет Федерации. Есть вопросы, пока не пошли дальше?",
    "continue": "Продолжаем обзор?",
    "continue_employer": "Переходим к работодателю?",
    "continue_fsp": "Переходим к кабинету Федерации?",
    "continue_public": "Переходим к разделу для технического жюри?",
    "continue_candidate": "Переходим к стороне кандидата?",
    "listen": "Слушаю вас.",
    "no_more": "Хорошо. Скажите, что показать, или «дальше» — продолжим обзор.",
    "remind": "Я здесь. Скажите, когда продолжим.",
    "remind_checkin": "Если вопросов нет, скажите «дальше».",
    "remind_start": "Скажите, что показать: весь сайт или ваш раздел — кандидат, работодатель или Федерация.",
    "skip_candidate": "Хорошо, тогда сторона кандидата.",
    "skip_employer": "Хорошо, тогда дальше — сторона работодателя.",
    "skip_fsp": "Хорошо, тогда дальше — кабинет Федерации.",
    "skip_public": "Хорошо, тогда дальше — раздел для технического жюри.",
    "skip_end": "Хорошо. Это был последний раздел. Спрашивайте или скажите, что показать.",
    "done_all": "Это главное о «Драфте». Спрашивайте о чём угодно или скажите, что показать подробнее.",
    "done_candidate": "Это главное для кандидата. Спросите о чём угодно или скажите «работодатель» — покажу вторую сторону.",
    "done_employer": "Так работодатель находит подтверждённых специалистов. Спрашивайте — или скажите «кандидат», покажу его путь.",
    "done_fsp": "Это кабинет Федерации. Спрашивайте, если что-то интересно.",
    "hello": "Здравствуйте. Как к вам обращаться?",
    "ask_role": "Показать весь сайт или начнём с вашей роли: кандидат, работодатель или Федерация?",
    "nomic": "Здравствуйте. Я Настя, ИИ-проводник по «Драфту». Микрофон недоступен, поэтому я просто проведу вас по сайту.",
}

# Персональные варианты ({name}); без имени — обычная фраза из PHRASES
PHRASES_NAMED: dict[str, str] = {
    "done_all": "{name}, это главное о «Драфте». Спрашивайте о чём угодно или скажите, что показать подробнее.",
    "done_candidate": "{name}, это главное для кандидата. Спросите о чём угодно или скажите «работодатель» — покажу вторую сторону.",
    "done_employer": "{name}, так работодатель находит подтверждённых специалистов. Спрашивайте — или скажите «кандидат», покажу его путь.",
}

FILLERS = ("Секунду.", "Так, смотрю.", "Сейчас.", "Одну секунду.")



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


def _arena_lines() -> list[str]:
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
    return [
        f"Арена ранжирования: в первой пятёрке Драфта подходящих кандидатов на {num_words(pp)} "
        f"{plural(pp, 'процентный пункт', 'процентных пункта', 'процентных пунктов')} больше, чем у поиска по резюме, "
        f"а раздутые резюме почти не попадают в первую десятку.",
        f"А здесь точность грейда: в пределах одной ступени — {within_txt}, и из {num_words(attacks, gen=True)} атак "
        f"на оценщика {tail}.",
    ]


def _arena_speech() -> str:  # совместимость: одной репликой
    return " ".join(_arena_lines())


STEP_BEATS: dict[str, list[str]] = {
    # ---- главная
    "home": [
        "Это «Драфт» — платформа обратного найма: специалист один раз подтверждает уровень, а компании приходят к нему сами.",
        "Три стороны: кандидат, работодатель и Федерация спортивного программирования. Пройдём по каждой.",
    ],
    # ---- кандидат (пункты меню по порядку)
    "cand-overview": [
        "Это кабинет кандидата. Здесь специалист один раз подтверждает уровень, а работодатели приходят к нему сами.",
        "Весь путь — четыре шага: стек, тест на грейд, устная защита и приглашения с зарплатой.",
        "Здесь видно интерес работодателей за неделю: сколько компаний открыли карточку и в скольких подборках вы есть.",
        "А это ИИ-адвокат зарплаты: он готовит обоснование встречного оффера на ваших фактах.",
        "Перейду ко второму шагу — тесту на грейд.",
    ],
    "cand-assessment": [
        "Сначала выбирают грейд, который хотите подтвердить, — от стажёра до Principal.",
        "Подсказка по стажу предлагает уровень, но выбор всегда за вами.",
        "Режимов два: полный тест и экспресс на пять–семь заданий.",
        "Тест адаптивный: каждое следующее задание подбирается по прошлым ответам, поэтому он короче обычного.",
    ],
    "cand-category": [
        "После теста — категория и грейд. Шкала показывает уровень и погрешность оценки: это психометрия, а не процент правильных.",
        "Ниже паспорт грейда с электронной подписью. Работодатель проверяет его по QR-коду за секунду, без звонков.",
        "Здесь же история грейда и пересдача — на уровень выше или ниже.",
    ],
    "cand-defense": [
        "У каждой попытки есть паспорт честности из пяти контуров. Вердикт видит работодатель, автоматических наказаний нет.",
        "А это устная защита: три минуты живого разговора с ИИ-интервьюером по вашим ответам. Скопированное из нейросети так не защитить.",
    ],
    "cand-feedback": [
        "Карта навыков подсказывает, что делать дальше: что подтянуть и какие задачи пройти.",
        "А здесь — что прямо сейчас просит рынок в вашей категории по открытым вакансиям.",
        "Ниже маршрут роста и соревнования Федерации, где можно подтвердить уровень.",
    ],
    "cand-profile": [
        "Профиль и резюме: контакты, резюме в PDF или DOCX с автораспознаванием и стандартный PDF-профиль.",
        "А это карточка «Как вас видит работодатель»: без имени, с номером, грейдом и отметками о защите. Контакты откроются только после вашего согласия.",
    ],
    "cand-invitations": [
        "В приглашениях компания всегда сразу называет зарплатную вилку.",
        "Приглашение можно принять, отклонить или предложить свою вилку. Контакты открываются только после вашего согласия.",
    ],
    "cand-messages": [
        "Сообщения — переписка с работодателями по приглашениям и откликам, внутри платформы.",
        "До принятия приглашения контакты скрыты: телефоны, почта и мессенджеры в чате маскируются.",
    ],
    "cand-trio": [
        "Связь с ФСП — трёхсторонний канал: вы, работодатель и представитель Федерации.",
        "Так подтверждают результаты соревнований и условия оффера. Подключить представителя можно только с вашего согласия.",
    ],
    "cand-cups": [
        "Кубки работодателей — соревнования компаний в вашей категории под их вакансии.",
        "Место в таблице результатов, приглашения лучшим и запись в паспорт ФСП.",
    ],
    "cand-fsp": [
        "Паспорт ФСП: профиль связывается с ФСП ID, достижения подтягиваются из реестра Федерации одной кнопкой.",
        "Индекс достижений показывает спортивный уровень по дисциплинам — работодатель видит его в карточке.",
    ],
    "cand-mydata": [
        "Мои данные: что о вас хранится и интерес работодателей за неделю.",
        "Выгрузка одним файлом, отзыв согласий и удаление учётной записи — всё по закону о персональных данных.",
    ],
    "cand-probes": [
        "Задания с вилкой — короткая задача от компании со свободным ответом и зарплатной вилкой ещё до раскрытия контактов.",
    ],
    "cand-assignments": [
        "Задания для вас — адресные задания с автопроверкой под ваш стек.",
        "Здесь же свежесть профиля и как часто предлагать вам такие задания.",
    ],
    "cand-settings": [
        "Настройки и приватность: какие поля попадают в обезличенную карточку.",
        "Скрытый минимум зарплаты и согласия по закону о персональных данных — тоже здесь.",
    ],
    "cand-vacancies": [
        "Вакансии — вакансии компаний, загруженные из их систем найма; на них можно откликнуться прямо здесь.",
    ],
    "cand-notifications": [
        "Уведомления: каналы — в браузере, на телефоне и почтой.",
        "И лента событий: приглашения, сообщения, результаты.",
    ],
    # ---- работодатель
    "emp-home": [
        "Это кабинет компании. Наверху тариф: сколько приглашений осталось.",
        "А это новинка — Командный Драфт: сборка целой команды под проект в один клик.",
        "Ниже — с чего начать: потребность, подборка, сравнение, приглашение.",
    ],
    "emp-needs": [
        "Работодатель начинает с потребности: текст вакансии можно вставить, надиктовать или загрузить файлом.",
        "Подставлю пример вакансии.",
        "Кнопка «Разобрать требования» выделит стек с цитатами и уберёт дискриминационные формулировки. Подборка собирается меньше чем за минуту.",
    ],
    "emp-compare": [
        "Это сравнение кандидатов. По каждому требованию видно, чем подтверждён навык: тестом, задачей или достижением ФСП.",
        "ИИ-советник руководителя коротко докладывает, кого позвать первым и о чём спросить на финальном созвоне.",
    ],
    "emp-squad": [
        "Командный Драфт собирает сбалансированную команду под проект и бюджет — от двух до десяти человек.",
        "Всей команде можно сразу отправить пакетный оффер.",
        "А рентген кода показывает, как кандидаты пишут на самом деле.",
    ],
    "emp-search": [
        "Поиск по базе: фильтры по специализации, грейду, категории, стеку и паспорту ФСП.",
        "Карточки кандидатов обезличены, но с историей тестов — контакты только после принятого приглашения.",
    ],
    "emp-invitations": [
        "Без зарплатной вилки приглашение отправить нельзя. Здесь видны встречные предложения кандидатов и переписка.",
        "Принятого кандидата можно в один клик передать в ATS компании.",
    ],
    "emp-messages": [
        "Сообщения — переписка с кандидатами по приглашениям и откликам. До принятия кандидат обезличен.",
    ],
    "emp-trio": [
        "Связь с ФСП — трёхсторонний канал по приглашению: вы, кандидат и представитель Федерации. Подтверждение результатов, условия, спорные вопросы.",
    ],
    "emp-ats": [
        "Интеграция с «Потоком» проверена на настоящем аккаунте: этапы найма возвращаются обратно, вплоть до выхода на работу.",
        "Здесь журнал передач и этапы из системы найма.",
    ],
    "emp-cups": [
        "Кубки — своё соревнование под вакансию на базе задания с вилкой: сроки, таблица результатов и приглашения лучшим.",
        "Решения оцениваются вслепую — без имён.",
    ],
    "emp-company": [
        "Профиль компании: данные, которые видят кандидаты, и текущий тариф.",
    ],
    "emp-probes": [
        "Задания с вилкой — короткая задача кандидату с зарплатной вилкой до раскрытия контактов.",
    ],
    "emp-assignments": [
        "Задания с автопроверкой: три–пять заданий банка по стеку потребности.",
        "Кандидату они приходят адресно, результат проверяется автоматически.",
    ],
    "emp-vacancies": [
        "Вакансии читаются из «Потока» только на чтение: импортированная вакансия становится потребностью.",
    ],
    "emp-notifications": [
        "Уведомления: каналы и лента событий — отклики, встречные предложения, принятые приглашения.",
    ],
    "emp-tariffs": [
        "Тарифы: «Старт» — бесплатно, три приглашения в месяц; «Найм» и «Партнёр ФСП» — по запросу.",
        "Партнёр ФСП входит в спонсорский пакет Федерации. Настоящей оплаты в демо нет — выставляется демонстрационный счёт.",
    ],
    # ---- Федерация
    "fsp-cabinet": [
        "Это кабинет Федерации спортивного программирования. Наверху — главное за выбранный период.",
        "Этот блок показывает, как победители соревнований получают приглашения от компаний.",
        "Ниже — воронка кандидатов и офферы в сравнении с рынком: видно, где люди отсеиваются и сколько им платят.",
        "Конвертер разряда переводит спортивный разряд в понятный работодателю ИТ-грейд.",
        "Открою спрос работодателей.",
    ],
    "fsp-demand": [
        "Спрос работодателей: какие категории и навыки ищут компании — потребности, приглашения и предложение кандидатов.",
        "Федерация видит только агрегаты: ни карточек, ни приглашений поштучно.",
    ],
    "fsp-effect": [
        "Эффект соревнований: как они влияют на приглашения и зарплаты — по направлениям, дисциплинам и разрядам.",
        "Всё выгружается в таблицу.",
    ],
    "fsp-salaries": [
        "Зарплаты из офферов: реальные вилки из приглашений против рынка по категориям.",
        "Это данные платформы, а не опросы.",
    ],
    "fsp-funnel": [
        "Воронки: путь от соревнования до приглашения и принятия.",
        "Отдельно — с достижениями ФСП и без них: видно, что даёт спортивный разряд.",
    ],
    "fsp-cups": [
        "Кубки работодателей как мероприятия платформы: участники, места, приглашения.",
    ],
    "fsp-trio": [
        "Трёхсторонняя связь: каналы с работодателями и кандидатами — подтверждение результатов соревнований, условия оффера, спорные вопросы.",
    ],
    "fsp-method": [
        "Методика и выгрузки: правила обезличивания, источники данных и таблицы CSV.",
        "Любую цифру кабинета можно проверить по методике.",
    ],
    "fsp-security": [
        "Безопасность входа: второй фактор — код из приложения-аутентификатора.",
    ],
    "fsp-benefit": [
        "Польза для ФСП: приглашения и наймы участников Федерации по регионам и направлениям.",
        "И вклад компаний-партнёров.",
    ],
    "fsp-partners": [
        "Партнёры ФСП: метка «Партнёр ФСП» компаниям из спонсорского пакета — заявки, выдача и снятие.",
    ],
    # ---- для жюри и общие страницы
    "warroom": [
        "Боевой ИИ-Полигон — для технического жюри.",
        "В первом режиме кандидат вживую чинит архитектуру высоконагруженной системы во время аварии.",
        "Во втором — атаки на ИИ-оценщика в один клик, и радар их перехватывает.",
    ],
    "val-arena": [
        "И как мы проверяем себя: пять чисел, у каждого указано, на каких данных оно получено.",
        # + две реплики арены — _arena_lines()
    ],
    "pricing": [
        "Тарифы и монетизация: для работодателей — «Старт» бесплатно, «Найм» и «Партнёр ФСП» по запросу; для Федерации — спонсорские пакеты.",
        "Ниже — как платформа зарабатывает.",
    ],
    "install": [
        "«Драфт» ставится на телефон как приложение — без магазинов, в один клик; есть и пакет для RuStore.",
    ],
}

STEP_IDS = tuple(STEP_BEATS.keys())


def beats() -> dict[str, list[str]]:
    out = {k: list(v) for k, v in STEP_BEATS.items()}
    out["val-arena"] = [*STEP_BEATS["val-arena"], *_arena_lines()]
    return out


def script(name: str | None = None) -> dict:
    b = beats()
    return {
        "name_ok": valid_stored_name(name),
        "greeting": GREETING, "greeting_back": GREETING_BACK, "nudge": NUDGE, "nudge_role": NUDGE_ROLE,
        "bridges": BRIDGES, "phrases": PHRASES, "phrases_named": PHRASES_NAMED, "fillers": list(FILLERS),
        "beats": b, "steps": {k: " ".join(v) for k, v in b.items()},  # steps — для старого фронта в кэше браузера
        "format": "pcm24", "rate": 24000, "version": 3,
        "max_minutes": MAX_MINUTES,   # потолок одного разговора (минуты видеопотока стоят денег)
    }


def script_texts() -> list[str]:
    sc = script()
    out = [sc["greeting"], sc["nudge"], sc["nudge_role"], *sc["phrases"].values(), *sc["fillers"]]
    out += [b[k] for b in sc["bridges"].values() for k in ("first", "next") if b.get(k)]
    for lines in sc["beats"].values():
        out += lines
    return list(dict.fromkeys(out))


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
        # mp3 — постоянные фразы и реплики шагов для браузера (в 6 раз меньше PCM), PCM 24 кГц — для потока ответа;
        # плюс типовые ответы на выбор роли без имени (звучат сразу, без синтеза)
        texts = script_texts()
        extra = [_start_reply(None, r, False, ft) for r in ROLES for ft in (True, False)]
        try:
            for text in [*texts, *extra]:
                for fmt in ("mp3", "pcm24"):
                    if fmt == "mp3" and text in extra:
                        continue
                    if cached(text, fmt):
                        continue
                    synth_bytes(text, fmt)
                    n += 1
        except TtsError as e:
            log.warning("concierge warm: %s", e)
        log.info("concierge warm: озвучено %d новых фраз", n)

    threading.Thread(target=run, name="concierge-warm", daemon=True).start()


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


# ------------------------------------------------------------------ понимание реплики

_NAME_RE = re.compile(
    r"(?:меня\s+зовут|мо[её]\s+имя|зовите\s+меня|зови\s+меня|обращайтесь\s+ко\s+мне|можно\s+просто|я\s+[-—–])\s*([А-ЯЁа-яё]{2,20})", re.I)
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
    "проведи", "проведите", "начни", "начните", "можешь", "можете", "умеешь", "слышишь", "слышите", "привет", "неважно",
    "никак", "любой", "любая", "пропустим", "потом", "хватит", "стой", "секунду", "минуту", "минутку", "извините",
    "простите", "понял", "поняла", "отлично", "прекрасно", "аналитик", "тестировщик", "менеджер", "жюри", "судья",
    "сразу", "быстро", "медленно", "коротко", "подробно", "показывай", "показывайте", "рассказывай", "рассказывайте",
    "нормально", "сначала", "дальше", "кабинет", "главная", "главную", "обзор", "тесты", "какой", "какая", "такое",
    "такой", "тоже", "вообще", "короче", "типа", "блин", "ой", "эм", "хм", "ага", "угу", "нету", "никто",
    "настя", "анастасия", "настенька", "настюша",   # так зовут саму Настю — обращение к ней, а не имя собеседника
}
# Своё имя Настя собеседнику не приписывает, кроме явного «меня зовут Настя»
_SELF_NAMES = {"настя", "анастасия", "настенька", "настюша"}


def _cap(name: str) -> str:
    return name[:1].upper() + name[1:].lower()


# Частые русские имена (полные и короткие формы): одно слово в ответ на «Как к вам обращаться?» — имя, только если оно
# здесь; «меня зовут …» / «зовите меня …» — любое слово, кроме служебных («сразу», «давай» и т. п. — не имена).
_NAMES = set("""
александр александра саша шура алексей лёша леша алёна алена алина алиса алла анастасия настя анатолий андрей
анжелика анна аня анечка антон арина арсений артём артем артур богдан борис вадим валентин валентина валерий валерия
варвара варя василий вася вера вероника виктор виктория вика виталий влад владимир вова володя владислав всеволод
вячеслав слава галина галя геннадий гена георгий гоша герман глеб григорий гриша давид дана данил даниил даня дарина
дарья даша денис диана дина дмитрий дима евгений евгения женя егор екатерина катя елена лена елизавета лиза эльвира
жанна захар зарина злата зоя иван ваня игорь илья инна ирина ира карина кира кирилл константин костя кристина ксения
ксюша лариса лев леонид лидия любовь люба людмила люда майя макар максим макс маргарита рита марина мария маша марк
матвей милана мирослава михаил миша надежда надя наталья наталия наташа никита николай коля нина оксана олег ольга оля
павел паша полина роман рома руслан сабина светлана света семён семен сергей серёжа сережа софия софья соня станислав
стас степан тамара тарас тимофей тимур татьяна таня ульяна фёдор федор филипп эдуард эмилия эрик юлия юля юрий юра
ян яна ярослав ярослава айгуль айдар альберт амир асель багира булат вагиз диляра динара ильдар ильнур камила камиль
ринат рустам тагир эльдар эльмира ахмед марат азат алсу гульнара лейла данияр нурлан ержан айжан асхат
""".split())
_NAME_RE2 = re.compile(r"(?:меня\s+([А-ЯЁа-яё]{2,20})\s+зовут|^\s*([А-ЯЁа-яё]{2,20})\s+меня\s+зовут)", re.I)
_NAME_ASK = re.compile(r"обращаться|как вас зовут|ваше имя|познакомимся", re.I)


def extract_name(text: str, current_name: str | None = None, asked: bool = False) -> str | None:
    """Имя из реплики. Явное «меня зовут…», «зовите меня…» меняет и уже известное имя; одно слово — имя, только если
    Настя только что спросила имя и слово есть в словаре имён."""
    t = (text or "").strip()
    m = _NAME_RE.search(t) or _NAME_RE2.search(t)
    if m:
        cand = next(g for g in m.groups() if g).strip()
        low = cand.lower()
        if (low not in _STOP_NAMES or low in _SELF_NAMES) and not low.startswith(("кандидат", "работодат")) \
                and (low in _NAMES or len(low) >= 3):
            return _cap(cand)
    if current_name:
        return current_name
    m = _SIMPLE_NAME_RE.match(t)
    if m:
        cand = m.group(1).strip()
        low = cand.lower().replace("ё", "е")
        # одно слово «Настя» — обращение к ней самой, не имя собеседника (своё имя — только через «меня зовут …»)
        if low in {n.replace("ё", "е") for n in _NAMES} and low not in _SELF_NAMES and (asked or len(_words(t)) == 1):
            return _cap(cand)
    return None


def valid_llm_name(name: str | None, message: str) -> str | None:
    """Имя от модели — только если оно прозвучало в реплике и похоже на имя."""
    if not name:
        return None
    n = name.strip().strip(".,!?").split()[0] if name.strip() else ""
    low = n.lower()
    if not n or len(low) < 2 or len(low) > 20:
        return None
    if low in _STOP_NAMES and not (low in _SELF_NAMES and (_NAME_RE.search(message or "") or _NAME_RE2.search(message or ""))):
        return None
    if low[:4] not in (message or "").lower():
        return None
    if low.replace("ё", "е") not in {x.replace("ё", "е") for x in _NAMES} and not (_NAME_RE.search(message or "") or _NAME_RE2.search(message or "")):
        return None
    return _cap(n)


def valid_stored_name(name: str | None) -> str | None:
    """Имя, запомненное в браузере с прошлого визита: только похожее на имя (одно слово из букв, не служебное слово
    вроде «Сразу»). Иначе None — тогда Настя знакомится заново."""
    n = (name or "").strip()
    if not n or len(n) > 20 or not re.fullmatch(r"[А-ЯЁа-яёA-Za-z-]{2,20}", n):
        return None
    low = n.lower()
    if low in _SELF_NAMES:
        return _cap(n)   # собеседницу тоже могут звать Настей — имя, записанное раньше, оставляем
    if low in _STOP_NAMES or low.replace("ё", "е") in {x.replace("ё", "е") for x in _STOP_NAMES}:
        return None
    if low.startswith(("кандидат", "работодат", "федерац")):
        return None
    return _cap(n)


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
    if re.search(r"весь сайт|вс[её] покаж|покажи(?:те)? (?:нам |мне )?(?:вс[её]|весь)\b|целиком|обзор|экскурс|жюри|"
                 r"эксперт|с самого начала|всю платформ|полностью", t):
        return "all"
    return None


# Порядок важен: сначала точные сочетания, потом общие слова. Для каждого пункта меню каждого кабинета — свой шаг.
_GOTO: list[tuple[str, str]] = [
    (r"арен|метрик|точност|бенчмарк|валидац|цифр|как вы проверяете", "val-arena"),
    (r"полигон|war ?room|вор ?рум", "warroom"),
    (r"тариф|монетизац|сколько стоит|цен[аы]\b|оплат", "tariffs"),
    (r"на телефон|приложени|rustore|рустор|установ", "install"),
    (r"главн\w* страниц|на главную|\bглавн(?:ую|ая)\b|домой|лендинг", "home"),
    # Федерация
    (r"спрос работодател|спрос компани|что ищут компани|спрос", "fsp-demand"),
    (r"эффект соревн|эффект", "fsp-effect"),
    (r"зарплат\w* из оффер|зарплаты из|офферы против рынка|зарплат\w* федерац", "fsp-salaries"),
    (r"воронк", "fsp-funnel"),
    (r"польз\w* для фсп|польз\w* федерац|польза", "fsp-benefit"),
    (r"партн[её]р", "fsp-partners"),
    (r"методик|выгрузк|csv|обезличиван", "fsp-method"),
    (r"безопасност\w* входа|второй фактор|двухфактор|аутентификатор|totp", "fsp-security"),
    (r"тр[её]хсторон\w* связ|связ\w* с фсп|связь с федерац|тр[её]хсторонн", "trio"),
    (r"кубк|кубок|хакатон", "cups"),
    # работодатель
    (r"командн\w* драфт|команд\w* под проект|собрать команд|сборн|звено|сквад", "emp-squad"),
    (r"\bats\b|\bатс\b|поток|хантфлоу|интеграци", "emp-ats"),
    (r"поиск по базе|поиск кандидат|база кандидат|поиск", "emp-search"),
    (r"сравн|советник", "emp-compare"),
    (r"потребност|разбор требован|подборк", "emp-needs"),
    (r"профил\w* компани|о компании|данные компании", "emp-company"),
    (r"задани\w* с автопроверк|автопроверк", "assignments"),
    (r"задани\w* с вилк|пробн\w* задани|задани", "probes"),
    (r"ваканси", "vacancies"),
    (r"уведомлен|пуш|push", "notifications"),
    (r"сообщени|переписк|чат", "messages"),
    (r"приглаш\w* (?:работодател|компани)|отправить приглаш|мои приглашения работодател", "emp-invitations"),
    # кандидат
    (r"паспорт\w* фсп|фсп id|фсп ид|достижени|индекс достижен", "cand-fsp"),
    (r"паспорт\w* грейд|\bqr\b|кью.?ар|подпис|категори|история грейда", "cand-category"),
    (r"защит|устн|интервьюер|честност|античит|попытк", "cand-defense"),
    (r"тест|грейд|опрос|стек", "cand-assessment"),
    (r"карт\w* навык|навык|маршрут рост|рост|что подтянуть", "cand-feedback"),
    (r"профил|резюме|как меня видит|как вас видит", "cand-profile"),
    (r"мои данные|персональн\w* данн|удалить аккаунт|152", "cand-mydata"),
    (r"настройк|приватност|скрытый минимум|согласи", "cand-settings"),
    (r"приглаш|оффер|вилк|торг", "cand-invitations"),
    # кабинеты целиком
    (r"кабинет фсп|кабинет федерац|федерац|\bфсп\b", "fsp-cabinet"),
    (r"кабинет кандидат|путь кандидат|сторон\w* кандидат|кандидат", "cand-overview"),
    (r"кабинет работодател|кабинет компани|работодател|компани", "emp-home"),
]

# Экраны, которые есть в нескольких кабинетах: какой открыть, зависит от текущего кабинета (или названного в реплике)
_SHARED: dict[str, dict[str, str]] = {
    "trio": {"candidate": "cand-trio", "employer": "emp-trio", "fsp": "fsp-trio"},
    "cups": {"candidate": "cand-cups", "employer": "emp-cups", "fsp": "fsp-cups"},
    "messages": {"candidate": "cand-messages", "employer": "emp-messages"},
    "notifications": {"candidate": "cand-notifications", "employer": "emp-notifications"},
    "vacancies": {"candidate": "cand-vacancies", "employer": "emp-vacancies"},
    "probes": {"candidate": "cand-probes", "employer": "emp-probes"},
    "assignments": {"candidate": "cand-assignments", "employer": "emp-assignments"},
    "tariffs": {"employer": "emp-tariffs"},
}
_SHARED_DEFAULT = {"trio": "cand-trio", "cups": "emp-cups", "messages": "cand-messages", "notifications": "cand-notifications",
                   "vacancies": "emp-vacancies", "probes": "emp-probes", "assignments": "emp-assignments", "tariffs": "pricing"}


def _cabinet_of_path(path: str | None, step: str | None = None) -> str | None:
    p = path or ""
    if step:
        if step.startswith("cand-"):
            return "candidate"
        if step.startswith("emp-"):
            return "employer"
        if step.startswith("fsp-"):
            return "fsp"
    if p.startswith("/candidate"):
        return "candidate"
    if p.startswith("/employer"):
        return "employer"
    if p.startswith("/fsp"):
        return "fsp"
    return None


def resolve_shared(sid: str, text: str, path: str | None, step: str | None) -> str:
    """Общий экран («сообщения», «кубки») → экран нужного кабинета: названного в реплике, иначе текущего, иначе типового."""
    if sid not in _SHARED:
        return sid
    t = (text or "").lower()
    if sid == "trio":   # «связь с ФСП» — название пункта, а не кабинет
        t = re.sub(r"связ\w*\s+с\s+(?:фсп|федерац\w*)|тр[её]хсторон\w*", " ", t)
    cab = None
    if re.search(r"работодател|компани", t):
        cab = "employer"
    elif re.search(r"кандидат", t):
        cab = "candidate"
    elif re.search(r"федерац|\bфсп\b", t):
        cab = "fsp"
    cab = cab or _cabinet_of_path(path, step)
    return _SHARED[sid].get(cab or "", None) or _SHARED_DEFAULT[sid]

_GOTO_VERB = re.compile(r"^(?:а\s+|ну\s+|так\s+|теперь\s+|настя\s+|давай(?:те)?\s+)*(?:покажи(?:те)?|открой(?:те)?|перейди(?:те)?|перейдём|перейдем|"
                        r"зайди(?:те)?|зайд[её]м|давай(?:те)?\s+(?:посмотрим|откроем|перейд[её]м)|хочу\s+(?:посмотреть|увидеть|открыть)|"
                        r"можно\s+(?:посмотреть|открыть|показать)|что\s+(?:там\s+)?(?:в|во|на)\s+(?:разделе|вкладке|пункте|экране))\b")


def detect_goto(text: str, *, strict: bool = True, path: str | None = None, step: str | None = None) -> str | None:
    t = _norm(text)
    if strict and not _GOTO_VERB.search(t):
        return None
    for rx, sid in _GOTO:
        if re.search(rx, t):
            return resolve_shared(sid, t, path, step)
    return None


def _words(text: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", (text or "").lower())


CMD_PAUSE = re.compile(r"^(?:ой\s+)?(?:стоп|пауза|подожди(?:те)?|погоди(?:те)?|секунду|минуту|минутку|остановись|"
                       r"остановитесь|замолчи|тише|хватит пока|не так быстро|постой(?:те)?|стой(?:те)?)\b")
CMD_RESUME = re.compile(r"^(?:ну\s+|да\s+|давай(?:те)?\s+)?(?:дальше|продолжа\w*|продолжим|поехали|вперёд|вперед|следующ\w*|"
                        r"давай(?:те)? дальше|идём дальше|идем дальше|едем дальше)\b")
CMD_REPEAT = re.compile(r"\b(?:повтори(?:те)?|ещё раз|еще раз|не расслышал\w*|что ты сказала|что вы сказали)\b")
CMD_BACK = re.compile(r"^(?:назад|вернись|вернитесь|верни(?:те)?|предыдущ\w*|обратно)\b")
CMD_BYE = re.compile(r"\b(?:до свидания|пока пока|закончим|заканчива\w*|заверш\w*|выключ\w*|закрой\w*|спасибо[, ]+всё|"
                     r"всё[, ]+спасибо|все[, ]+спасибо|больше не надо|на этом вс[её]|хватит на сегодня)\b")
HELLO = re.compile(r"^(?:привет\w*|здравствуй\w*|здрасте|добрый\s+(?:день|вечер)|доброе\s+утро|доброго\s+дня|"
                   r"хай|алло|ал[её]|салют|приветствую)\b")
YES = re.compile(r"^(?:ну\s+)?(?:да|ага|угу|конечно|давай(?:те)?|хорошо|окей|ок|ладно|можно|показывай(?:те)?|покажи(?:те)?|хочу)"
                 r"(?:\s+(?:да|давай(?:те)?|конечно|покажи(?:те)?|показывай(?:те)?|можно|пожалуйста|хорошо|интересно|хочу))*[\s,.!]*$")
# ответ на «Есть вопросы?» между разделами: «нет, дальше» — идём дальше; «да», «есть» — слушаем вопрос
CHECKIN_NO = re.compile(r"^(?:ну\s+|да\s+нет\s+|нет\s+)?(?:нет|нету|неа|нет вопросов|вопросов нет|никаких|всё понятно|все понятно|"
                        r"понятно|ясно|всё ясно|все ясно|пока нет|дальше|давай(?:те)?(?:\s+дальше)?|поехали|переходим|переходи\w*|"
                        r"пойд[её]м(?:\s+дальше)?|ид[её]м(?:\s+дальше)?|продолжа\w*|продолжим|можно дальше|вперёд|вперед)"
                        r"(?:[\s,.]+(?:нет|давай(?:те)?|дальше|спасибо|всё понятно|все понятно|понятно|переходим|продолжаем|поехали))*[\s,.!]*$")
CHECKIN_YES = re.compile(r"^(?:ну\s+)?(?:да|есть|ага|угу|да есть|есть вопрос|есть один|есть пара|да есть вопрос|один вопрос|"
                         r"есть вопросы|да вопрос)[\s,.!]*$")
CMD_NO = re.compile(r"^(?:ну\s+)?(?:нет|неа|не надо|не нужно|не хочу|пока нет|не сейчас|не стоит)(?:[\s,]+(?:спасибо|пока))?[\s,.!]*$")
CMD_SKIP = re.compile(r"^(?:(?:ну|давай(?:те)?|так|а|можно)\s+)*(?:пропусти\w*|пропустим|пропускаем|следующий раздел|другой раздел|"
                      r"не про это|не надо про это|это не надо|это неинтересно|это не интересно|неинтересно|не интересно|"
                      r"мне это не надо|мне это не нужно|дальше другое)(?:\s+(?:пожалуйста|это|раздел|его))*[\s,.!?]*$")
BYE_SHORT = re.compile(r"^(?:ну\s+)?(?:пока|до встречи|всего доброго|всего хорошего)(?:\s+пока)?$")
QUESTION = re.compile(r"\?|^(?:а\s+)?(?:почему|зачем|сколько|откуда|какой|какая|какие|каким|как|что|чем|кто|где|когда|"
                      r"можно ли|правда|расскажи|расскажите|объясни|объясните)\b")


def _norm(text: str) -> str:
    return " ".join(_words(text))


INTERJ = re.compile(r"^\s*(?:ой[\s,]+)?(?:подожди(?:те)?|погоди(?:те)?|стоп|стой(?:те)?|секунд(?:у|очку)|минуту|"
                    r"постой(?:те)?|извините|простите|настя|анастасия|елена|лена|слушай(?:те)?)[\s,.!—-]+(?:(?:а|и|но|ну|так|пожалуйста)[\s,]+)?",
                    re.IGNORECASE)


def strip_interjection(message: str) -> str:
    """«Подождите, а сколько длится тест?» → «сколько длится тест?»: просьба подождать перед вопросом — не пауза обзора;
    «Настя, покажи тест» → «покажи тест»: обращение по имени — не имя собеседника."""
    m = INTERJ.match(message or "")
    if not m:
        return message
    rest = message[m.end():].strip()
    return rest if len(_words(rest)) >= 2 else message


def classify(message: str, *, touring: bool, paused: bool) -> dict | None:
    """Мгновенное решение без модели или None (нужна модель)."""
    t = _norm(message)
    if not t:
        return None
    n = len(t.split())
    raw = (message or "").strip().lower()
    if (n <= 6 and CMD_BYE.search(t) and not QUESTION.search(raw)) or BYE_SHORT.search(t):
        return {"action": "end", "phrase": "bye"}
    if n <= 4 and CMD_PAUSE.search(t):
        return {"action": "pause", "phrase": "pause"}
    if n <= 4 and CMD_BACK.search(t) and (touring or paused):
        return {"action": "prev"}
    if n <= 5 and CMD_REPEAT.search(t):
        return {"action": "repeat"}
    if n <= 4 and CMD_RESUME.search(t):
        return {"action": "resume"}
    if (paused or touring) and n <= 3 and YES.search(t):
        return {"action": "resume"}
    return None


def _offered(last_said: str) -> bool:
    """Последняя реплика Насти — предложение обзора (тогда «да» значит «начинай обзор»). «Показать, как это
    выглядит?» без экрана — не обзор: такое «да» решает модель по ходу разговора."""
    t = (last_said or "").lower()
    return "?" in t and bool(re.search(r"весь сайт|обзор|по шагам|с вашей роли|кандидат, работодатель|начн[её]м\?", t))


GO_BARE = re.compile(r"^(?:(?:ну|сразу|просто|давай(?:те)?|тогда|уже)\s+)*(?:покажи(?:те)?|показывай(?:те)?|начинай(?:те)?|"
                     r"поехали|веди(?:те)?|проведи(?:те)?|рассказывай(?:те)?)(?:\s+(?:всё|все|сразу|уже|пожалуйста))*$")


def _start_reply(name: str | None, role: Role, first_time: bool, first_tour: bool = False) -> str:
    who = {"candidate": "путь кандидата", "employer": "кабинет работодателя",
           "fsp": "кабинет Федерации", "all": "весь сайт по шагам"}[role]
    tail = " Спрашивайте в любой момент." if first_tour else ""
    if name and first_time:
        return f"Очень приятно, {name}. Показываю {who}.{tail}"
    if name:
        return f"{name}, показываю {who}.{tail}"
    return f"Хорошо, показываю {who}.{tail}"


def _clean_reply(text: str) -> str:
    t = re.sub(r"[*#`_~\"]+", "", str(text or ""))
    t = re.sub(r"\s*\([^)]{0,80}\)", "", t)          # скобки голосом не читаются
    t = re.sub(r"\s*\[[^\]]{0,120}\]", "", t)        # служебные пометки истории — не для голоса
    t = t.replace("%", " процентов").replace("@", " ")
    t = re.sub(r"!", ".", t)
    t = re.sub(r"\b(?:ElevenLabs|Anam|Deepgram|OpenRouter|WebRTC|Claude|Anthropic|Gemini|GPT|OpenAI)\b", "", t, flags=re.I)
    t = " ".join(t.split()).strip()
    return _brief(t)


_SELF_TALK = re.compile(r"^[^.?]*\b(?:я|меня)\b[^.?]*\b(?:торопил|поторопил|сбил|запутал|перебил|ошиблас|увлеклас|спешил)\w*[^.?]*\.\s*",
                        re.I)


def _drop_self_talk(t: str) -> str:
    """«Понимаю, я немного торопилась.» в начале ответа — убираем: Настя не оправдывается, а отвечает по делу."""
    rest = _SELF_TALK.sub("", t, count=1).strip()
    return rest[:1].upper() + rest[1:] if len(rest) >= 12 else t


def _brief(t: str, limit: int = 250) -> str:
    """Голосом — коротко: целые предложения в пределах limit знаков; вопрос-предложение в конце сохраняем."""
    if len(t) <= limit:
        return t
    sents = [x.strip() for x in re.split(r"(?<=[.?…])\s+", t) if x.strip()]
    if not sents:
        return t[:limit]
    out = [sents[0]]
    for x in sents[1:]:
        if len(" ".join([*out, x])) > limit:
            break
        out.append(x)
    last = sents[-1]
    if last.endswith("?") and last not in out and len(" ".join([*out, last])) <= limit + 40:
        out.append(last)
    res = " ".join(out)
    if len(res) > limit + 60:  # одно огромное предложение — по запятой
        cut = res.rfind(", ", 0, limit)
        res = (res[:cut] if cut > 60 else res[:limit].rsplit(" ", 1)[0]) + "."
    return res


def turn(message: str, *, user_name: str | None = None, role: str | None = None, current_path: str = "/",
         step_id: str | None = None, touring: bool = False, paused: bool = False, history: list[dict] | None = None,
         session_id: str | None = None, screen: dict | None = None, last_said: str = "", awaiting: str | None = None,
         on_ack=None, no_llm: bool = False) -> dict:
    """Решение по законченному ходу собеседника.

    Возвращает {reply, phrase, action, role, step, point, user_name, kind}. phrase — ключ постоянной фразы (если reply
    пустой). action: ask_role | start_tour | goto | point | answer | next_section | listen | pause | resume | repeat |
    prev | end. awaiting — чего ждёт Настя: checkin («Есть вопросы?» между разделами), continue («Продолжаем?»),
    detour («Вернёмся к обзору?»), start (что показать) или None.
    Простые команды («стоп», «дальше», «повтори», выбор роли до обзора) — мгновенно, остальное — модель с базой знаний.
    """
    from app.modules.interview import concierge_brain as brain

    s = brain.session(session_id)
    msg = strip_interjection((message or "").strip())
    user_name = valid_stored_name(user_name)
    known = user_name or (valid_stored_name(s.name) if s else None)
    asked = bool(_NAME_ASK.search(last_said or "")) or bool(s and _NAME_ASK.search(s.last_elena or ""))
    name_now = extract_name(msg, known, asked)
    name = name_now or known
    first_time = bool(name_now and name_now != known)
    cur_role = role if role in ROLES else (s.role if s and s.role in ROLES else None)
    words_n = len(_words(msg))
    is_q = bool(QUESTION.search(msg.lower())) and words_n > 1
    first_tour = bool(s is not None and not s.shown)

    def ack(kind: str) -> None:
        if on_ack:
            on_ack(kind)

    base = {"user_name": name, "role": cur_role, "step": None, "point": None, "reply": "", "phrase": None}
    # «да», «показывай» в ответ на предложение Насти («Показать …?») — сразу делаем предложенное
    offer = s.offer if s and isinstance(s.offer, dict) and time.time() - float(s.offer.get("at", 0)) < 120 else None
    if offer and (awaiting in ("checkin", "continue", "detour") or
                  (offer.get("text") and last_said and last_said.strip() != str(offer["text"]).strip())):
        offer = None   # после предложения Настя уже сказала другое — «да» относится к последнему вопросу
    if offer and words_n <= 4 and YES.search(_norm(msg)):
        ack("instant")
        act = offer.get("action")
        if act == "start_tour":
            r = offer.get("role") if offer.get("role") in ROLES else (cur_role or "all")
            return {**base, "kind": "instant", "action": "start_tour", "role": r, "reply": _start_reply(name, r, False, first_tour)}
        if act == "goto" and offer.get("step") in STEP_IDS:
            return {**base, "kind": "instant", "action": "goto", "step": offer["step"], "phrase": "goto"}
        if act == "point" and offer.get("point"):
            return {**base, "kind": "instant", "action": "point", "point": offer["point"], "reply": "Вот здесь."}
    t_norm = _norm(msg)
    if awaiting == "checkin" and words_n <= 6:
        if CHECKIN_NO.search(t_norm):
            ack("instant")
            return {**base, "kind": "instant", "action": "resume"}
        if CHECKIN_YES.search(t_norm):
            ack("instant")
            return {**base, "kind": "instant", "action": "listen", "phrase": "listen"}
    if awaiting in ("continue", "detour") and words_n <= 5 and CMD_NO.search(t_norm):
        ack("instant")
        return {**base, "kind": "instant", "action": "pause", "phrase": "no_more"}
    if (touring or paused) and words_n <= 7 and CMD_SKIP.search(t_norm):
        ack("instant")
        nxt = brain.next_section(step_id)
        return {**base, "kind": "instant", "action": "next_section", "phrase": f"skip_{nxt}" if nxt else "skip_end"}
    if first_time and (touring or paused) and words_n <= 4 and not is_q:
        # назвался посреди обзора — знакомимся и продолжаем с того же места
        ack("instant")
        return {**base, "kind": "instant", "action": "resume", "reply": f"Очень приятно, {name}."}
    quick = classify(msg, touring=touring, paused=paused)
    if quick:
        ack("instant")
        out = {**base, "kind": "instant", "action": quick["action"]}
        if quick.get("phrase"):
            out["phrase"] = quick["phrase"]
        return out

    if not touring and not paused and not is_q and words_n <= 5 and GO_BARE.search(_norm(msg)):
        r = cur_role or "all"   # «сразу покажи», «поехали» без уточнения — обзор (своей роли или всего сайта)
        ack("instant")
        return {**base, "kind": "instant", "action": "start_tour", "role": r, "reply": _start_reply(name, r, first_time, first_tour)}
    if not touring and not paused and not is_q and words_n <= 6:
        det = detect_role(msg)
        if det:
            ack("instant")
            return {**base, "kind": "instant", "action": "start_tour", "role": det,
                    "reply": _start_reply(name, det, first_time, first_tour)}
        if HELLO.search(_norm(msg)) and words_n <= 3 and not first_time:
            ack("instant")
            return {**base, "kind": "instant", "action": "ask_role",
                    "reply": f"Здравствуйте, {name}. {PHRASES['ask_role']}" if name else "", "phrase": None if name else "hello"}
        if YES.search(_norm(msg)) and _offered(last_said):
            r = cur_role or "all"
            ack("instant")
            return {**base, "kind": "instant", "action": "start_tour", "role": r,
                    "reply": _start_reply(name, r, False, first_tour)}
        if first_time and words_n <= 4:
            ack("instant")
            return {**base, "kind": "instant", "action": "ask_role", "reply": f"Очень приятно, {name}. {PHRASES['ask_role']}"}
    goto = detect_goto(msg, path=current_path, step=step_id) if not is_q and words_n <= 7 else None
    if goto:
        ack("instant")
        return {**base, "kind": "instant", "action": "goto", "step": goto, "phrase": "goto"}

    if no_llm:
        # дневной лимит ходов модели исчерпан — без модели: экран по словам реплики или ответ из базы знаний
        ack("instant")
        g = detect_goto(msg, strict=False, path=current_path, step=step_id)
        if g and not is_q:
            return {**base, "kind": "fallback", "action": "goto", "step": g, "phrase": "goto"}
        return {**base, "kind": "fallback", "action": "answer", "reply": _kb_answer(msg, current_path, step_id)}
    ack("llm")
    d = brain.answer(msg, sid=session_id, name=name, role=cur_role, path=current_path, step=step_id, touring=touring,
                     paused=paused, screen=screen, history=history, awaiting=awaiting, last_said=last_said,
                     numbers=numbers_chunk() if re.search(r"точн|цифр|процент|метрик|арен|провер|валидац|bm25|атак",
                                                          msg.lower()) or current_path.startswith("/validation") else None)
    if not d:
        g = detect_goto(msg, strict=False, path=current_path, step=step_id)
        if g:
            return {**base, "kind": "fallback", "action": "goto", "step": g, "phrase": "goto"}
        return {**base, "kind": "fallback", "action": "answer", "reply": _kb_answer(msg, current_path, step_id)}
    reply = _drop_self_talk(_clean_reply(d.get("reply", "")))
    if name and reply.lower().startswith(name.lower() + ","):
        # имя — не в каждой реплике: звучало в двух последних — убираем обращение
        recent = [h["text"] for h in ((s.history if s else None) or history or []) if h.get("who") == "elena"][-2:]
        if any(name.lower() in t.lower() for t in recent):
            rest = reply[len(name) + 1:].lstrip()
            reply = rest[:1].upper() + rest[1:] if rest else reply
    action = d.get("action") if d.get("action") in ("answer", "start_tour", "goto", "point", "next_section", "pause",
                                                     "resume", "end") else "answer"
    if action == "next_section" and not (touring or paused):
        action = "answer"
    llm_role = d.get("role") if d.get("role") in ROLES else None
    step = d.get("step") if d.get("step") in STEP_IDS else None
    point = d.get("point") if isinstance(d.get("point"), str) and 1 <= len(d["point"].strip()) <= 80 else None
    llm_name = valid_llm_name(d.get("user_name") if isinstance(d.get("user_name"), str) else None, msg)
    if action == "goto" and not step:
        action = "answer"
    if action == "point" and not point:
        action = "answer"
    if action == "start_tour" and not (llm_role or cur_role):
        llm_role = "all"
    if action == "start_tour" and (touring or paused) and (llm_role or "all") == (cur_role or "all"):
        action = "resume"   # тот же обзор уже идёт — продолжаем, а не начинаем заново
    new_offer = None
    if action == "answer" and reply.rstrip().endswith("?") and (step or point):
        action = "point" if point and not step else "goto"   # «Показать …?» с шагом — это предложение показать
    if action == "answer" and reply.rstrip().endswith("?") and not step and not point:
        last_q = re.split(r"(?<=[.!…])\s+", reply.strip())[-1].lower()
        if re.search(r"показать|покажу|открыть|открою|посмотр|провести|провед", last_q):
            g = detect_goto(last_q, strict=False, path=current_path, step=step_id)
            if g:
                step, action = g, "goto"
            elif re.search(r"весь сайт|обзор|по шагам|всю платформ", last_q):
                action, llm_role = "start_tour", llm_role or cur_role or "all"
    if action in ("goto", "start_tour", "point") and reply.rstrip().endswith("?"):
        # предложила («Показать …?») — не делаем сами, ждём согласия; «да» выполнит предложенное
        new_offer = {"action": action, "step": step, "role": llm_role, "point": point, "at": time.time(), "text": reply}
        action = "answer"
    new_name = name or llm_name
    return {
        "offer": new_offer,
        "user_name": new_name,
        "role": llm_role or cur_role,
        "step": step,
        "point": point.strip() if point else None,
        "reply": reply,
        "phrase": None,
        "action": action,
        "kind": "llm",
        "model": d.get("_model"),
        "llm_ms": d.get("_ms"),
    }


def _kb_answer(msg: str, path: str, step: str | None) -> str:
    """Модели не ответили вовремя — ответ из базы знаний: предложения самого подходящего блока, где есть слова вопроса."""
    from app.modules.interview import concierge_rag as rag

    try:
        chunks = rag.retrieve(msg, current_path=path, step=step, k=2)
    except Exception:  # noqa: BLE001
        chunks = []
    common = set(rag.tokens("кандидат кандидаты работодатель работодатели драфт платформа сайт федерация фсп экран"))
    q = set(rag.tokens(msg)) - common
    for c in chunks:
        sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", c.text) if len(x.strip()) > 25]
        best = sorted(sents, key=lambda x: -len(q & set(rag.tokens(x))))[:2]
        best = [x for x in best if q & set(rag.tokens(x))]
        if best:
            return _brief(" ".join(best), 240)
    return "Скажу коротко: это лучше один раз увидеть. Скажите, какой экран открыть, — покажу."


_TURNS_HOUR: list[float] = []
_TURNS_LOCK = threading.Lock()
TURNS_PER_HOUR = int(os.environ.get("CONCIERGE_TURNS_PER_HOUR", "1500"))


def _allow_turn() -> bool:
    now = time.time()
    with _TURNS_LOCK:
        while _TURNS_HOUR and now - _TURNS_HOUR[0] > 3600:
            _TURNS_HOUR.pop(0)
        if len(_TURNS_HOUR) >= TURNS_PER_HOUR:
            return False
        _TURNS_HOUR.append(now)
        return True


def turn_stream(message: str, **kw) -> Iterator[bytes]:
    """NDJSON: ack → meta → pcm… → end. Любой сбой голоса — {"t": "voice_error"}, фронт скажет текст своим откатом."""
    import queue

    from app.modules.interview import concierge_brain as brain

    t0 = time.monotonic()
    q: queue.Queue = queue.Queue()
    box: dict = {}
    sid = kw.get("session_id")

    def work() -> None:
        try:
            if not _allow_turn():
                box["res"] = {"user_name": kw.get("user_name"), "role": kw.get("role"), "step": None, "kind": "fallback",
                              "action": "answer", "phrase": None,
                              "reply": "Сейчас со мной говорит очень много людей. Давайте я просто покажу сайт — скажите «дальше»."}
                return
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
    decided_ms = int((time.monotonic() - t0) * 1000)
    meta = {"t": "meta", **{k: v for k, v in res.items() if k not in ("model", "llm_ms", "offer")}, "text": text, "ms": decided_ms}
    yield (json.dumps(meta, ensure_ascii=False) + "\n").encode()
    with brain.mutate(sid) as sess:
        if sess is not None:
            sess.turns += 1
            sess.offer = res.get("offer")
            if res.get("user_name"):
                sess.name = res["user_name"]
            sess.remember("user", message)
            if text:
                note = ""
                if res.get("action") == "goto" and res.get("step"):
                    note = f" [открываю экран: {brain.STEP_TITLES.get(res['step'], res['step'])}]"
                elif res.get("action") == "start_tour":
                    note = " [начинаю обзор]"
                sess.remember("elena", text + note)
            if res.get("role") and res.get("action") == "start_tour":
                sess.role = res["role"]
    if sess is not None:
        brain.write(sess, "user", message, path=kw.get("current_path"), step=kw.get("step_id"),
                    touring=kw.get("touring") or None, paused=kw.get("paused") or None)
        brain.write(sess, "elena", text, kind=res.get("kind"), action=res.get("action"), step=res.get("step"),
                    role=res.get("role") if res.get("action") == "start_tour" else None, point=res.get("point"),
                    model=res.get("model"), ms=decided_ms)
        if res.get("kind") in ("llm", "fallback") or sess.turns % 3 == 0:
            brain.supervise_async(sid)
    first_audio = None
    if text:
        try:
            for chunk in synth_stream(text, "pcm24"):
                if first_audio is None:
                    first_audio = int((time.monotonic() - t0) * 1000)
                yield (json.dumps({"t": "pcm", "b64": base64.b64encode(chunk).decode()}) + "\n").encode()
        except TtsError as e:
            yield (json.dumps({"t": "voice_error", "v": str(e)}) + "\n").encode()
    yield (json.dumps({"t": "end", "ms": int((time.monotonic() - t0) * 1000)}) + "\n").encode()
    log.info("concierge turn: %s/%s решение %d мс, голос %s мс, модель %s", res.get("kind"), res.get("action"), decided_ms,
             first_audio, res.get("model") or "—")


# ------------------------------------------------------------------ совместимость: /concierge/chat (старый фронт)

def reply_chat(message: str, *, user_name: str | None = None, user_role: str | None = None, current_path: str = "/",
               step_index: int = 0, history: list[dict] | None = None) -> dict:
    res = turn(message, user_name=user_name, role=user_role, current_path=current_path, history=history)
    text = res.get("reply") or (PHRASES.get(res["phrase"]) if res.get("phrase") else "") or PHRASES["goto"]
    return {
        "reply": text,
        "user_name": res.get("user_name"),
        "detected_role": res.get("role") or "all",
        "start_tour": res.get("action") in ("start_tour", "goto", "resume"),
        "jump_to_step": None,
    }

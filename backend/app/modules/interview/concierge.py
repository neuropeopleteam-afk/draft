"""Живой ИИ-проводник Елена (Anam WebRTC липсинк + голос ElevenLabs + распознавание Deepgram + диалог через LLM).

Работает на главной странице и во всех кабинетах без привязки к сессии теста кандидата:
1. avatar_token() — одноразовый токен потока Anam (cara-4, enableAudioPassthrough=True) + наши TURN-серверы;
2. speak(text, fmt) — синтез речи ElevenLabs (mp3 или pcm_16000 для липсинка Anam) с кэшированием в памяти;
3. transcribe(audio, mime) — распознавание русской речи через Deepgram Nova-2;
4. chat(...) — живой диалог: знакомство по имени, определение роли, ответы на любые вопросы о платформе «Драфт».
"""
from __future__ import annotations

from functools import lru_cache
import re
from typing import Literal

from app.modules.interview import port as pt
from app.modules.interview.engine.settings import get_interview_settings

SYSTEM_PROMPT = """Ты — Елена, живой голосовой ИИ-проводник и консультант платформы обратного найма «Драфт» (Всероссийская федерация спортивного программирования, ФСП).
Твоя задача — тепло, умно и лаконично общаться с пользователем голосом (2–3 коротких предложения, без списков, звёздочек и разметки Markdown, чтобы речь звучала естественно при озвучке ElevenLabs).

Ключевые факты о платформе «Драфт», которые ты знаешь досконально:
1. Суть: «Драфт» заменяет субъективные резюме и отклики на доказательную оценку. Специалист один раз сдаёт адаптивный тест и получает категорию «направление · грейд» (например, Backend · Middle), а работодатели сами присылают приглашения с обязательной зарплатной вилкой в рублях. Контакты кандидата скрыты (код C-...) до его согласия.
2. Стек под капотом:
   - Психометрия 2PL IRT: оценка способности тета (от -2,5 до +2,5) методом максимального апостериорного правдоподобия (MAP, Ньютон — Рафсон), выбор следующей задачи по максимуму информации Фишера.
   - Защита от списывания: 6 поведенческих сигналов (вставки, уход со вкладки, время ответа, почерк набора), браузерная нейросеть камеры MediaPipe Tasks Vision 0.10.32 (кадры не покидают устройство) и 3-минутная устная защита кода с ИИ-аватаром по WebRTC.
   - Многофакторное ранжирование кандидатов: 45 % — тест 2PL IRT, 35 % — подтверждённый обязательный стек, 10 % — спортивные достижения из реестра ФСП, 5 % — проверочные задачи, 5 % — желательный стек. Точность топа P@5 = 77,6 %.
   - Рынок hh.ru и ТК РФ: в базе 1 344 открытые вакансии Backend в РФ, автоматический фильтр дискриминации по ст. 64 ТК РФ.
3. Как вести диалог:
   - Если пользователь назвал своё имя — обязательно обращайся к нему по имени.
   - Отвечай по существу заданного вопроса простыми и ясными словами, а в конце фразы мягко предлагай продолжить экскурсию по экрану.
   - Пиши только чистый русский текст для произнесения вслух (без кавычек-ёлочек вокруг всей фразы, без списков и символов * или #).
"""

_NAME_RE = re.compile(
    r"(?:меня\s+зовут|я\s+—|я\s+-|мо[её]\s+имя|зови\s+меня|обращайся\s+ко\s+мне)\s+([А-ЯЁа-яёA-Za-z]{2,20})",
    re.I,
)
_SIMPLE_NAME_RE = re.compile(r"^\s*([А-ЯЁа-яё]{2,18})(?:[\s,!.]+(?:я|мне|покажи|кандидат|работодатель|жюри|эксперт|давай|привет).*)?$", re.I)

_STOP_NAMES = {
    "привет", "здравствуйте", "добрый", "покажи", "расскажи", "кандидат", "работодатель",
    "компания", "федерация", "эксперт", "жюри", "давай", "хочу", "кто", "что", "как", "где",
    "зачем", "почему", "дальше", "стоп", "пауза", "весь", "сайт", "просто", "ничего",
}


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
    if any(w in t for w in ("работодат", "компан", "нанима", "эйчар", "hr", "ваканс", "подборк")):
        return "employer"
    if any(w in t for w in ("фсп", "федерац", "аналитик", "спорт")):
        return "fsp"
    if any(w in t for w in ("кандидат", "разработч", "соискат", "специалист", "тест")):
        return "candidate"
    if any(w in t for w in ("жюри", "эксперт", "весь", "всё", "все", "полн", "сначала", "давай", "начин", "покажи")):
        return "all"
    return None


def detect_step_jump(text: str) -> int | None:
    t = (text or "").lower()
    if "закон" in t or "главн" in t:
        return 0
    if "тест" in t or "опрос" in t or "грейд" in t:
        return 4
    if "карт" in t or "навык" in t or "шкал" in t or "irt" in t:
        return 5
    if "потребн" in t or "ваканс" in t or "работодат" in t:
        return 6
    if "сравн" in t or "советник" in t:
        return 8
    if "фсп" in t or "федерац" in t:
        return 9
    return None


@lru_cache(maxsize=128)
def cached_speak(text: str, fmt: Literal["mp3", "pcm_16000"]) -> tuple[bytes, str]:
    audio, mime, _usd = pt.get_port().speak(text, fmt)
    return audio, mime


def reply_chat(
    message: str,
    *,
    user_name: str | None = None,
    user_role: str | None = None,
    current_path: str = "/",
    step_index: int = 0,
    history: list[dict] | None = None,
) -> dict:
    name = extract_name(message, user_name)
    role = detect_role(message) or (user_role if user_role in ("all", "candidate", "employer", "fsp") else None)
    jump = detect_step_jump(message)

    role_label = {
        "candidate": "кандидата",
        "employer": "работодателя",
        "fsp": "Федерации спортивного программирования",
        "all": "эксперта (полный маршрут по всей платформе)",
    }.get(role or "all", "полный маршрут по платформе")

    context_line = (
        f"Имя собеседника: {name or 'пока не названо'}. "
        f"Выбранная роль/маршрут: {role_label}. "
        f"Текущий экран сайта: {current_path} (шаг экскурсии №{step_index + 1})."
    )

    msgs: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + context_line},
    ]
    for h in (history or [])[-6:]:
        w = "assistant" if h.get("who") == "elena" else "user"
        c = str(h.get("text") or "").strip()
        if c:
            msgs.append({"role": w, "content": c[:600]})
    msgs.append({"role": "user", "content": message.strip()[:1000]})

    reply_text: str | None = None
    try:
        from app.modules.llm import client as llm

        s = get_interview_settings()
        res = llm.chat(
            msgs,
            temperature=0.5,
            max_tokens=260,
            want_json=False,
            model=s.interview_model_turn,
            timeout_s=10.0,
        )
        if res.ok and isinstance(res.text, str) and len(res.text.strip()) >= 10:
            cleaned = re.sub(r"[*#`_~]+", "", res.text).strip()
            cleaned = " ".join(cleaned.split())
            if len(cleaned) > 20:
                reply_text = cleaned[:480]
    except Exception:
        reply_text = None

    if not reply_text:
        greet = f"Очень приятно, {name}. " if name and not user_name else (f"{name}, " if name else "")
        if role == "employer":
            reply_text = (
                f"{greet}Отлично, посмотрим на платформу глазами работодателя. "
                "Сейчас я сначала покажу ключевые блоки на главной странице, а затем мы плавно перейдём в кабинет компании к разбору вакансии и подборке кандидатов."
            )
        elif role == "candidate":
            reply_text = (
                f"{greet}Замечательно, пройдём путь кандидата от начала до конца. "
                "Сначала я кратко покажу устройство платформы на главной странице, а затем переведу вас в кабинет специалиста к адаптивному тесту и карте навыков."
            )
        elif role == "fsp":
            reply_text = (
                f"{greet}Хорошо, я покажу аналитический контур Федерации спортивного программирования и то, как он связан с кандидатами и работодателями."
            )
        else:
            reply_text = (
                f"{greet}Договорились, я проведу вас по всей платформе шаг за шагом, начиная прямо с главной страницы, и стрелкой покажу каждый блок и каждое поле."
            )

    return {
        "reply": reply_text,
        "user_name": name,
        "detected_role": role or "all",
        "start_tour": True,
        "jump_to_step": jump,
    }

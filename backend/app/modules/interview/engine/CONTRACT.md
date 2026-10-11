# Движок ИИ-интервьюера «Драфта» — интерфейс для модуля interview (Я15)

Версия 1.0 · 10.10.2026 · владелец — Я14 (`feat/interview-engine`). Пакет `app.modules.interview.engine` — чистый Python
внутри backend; **без БД, без роутеров, без FastAPI**: состояние (расшифровка, план) принимает и возвращает структурами,
хранит его модуль interview (Я15). Все схемы — pydantic (`engine/schemas.py`), все функции синхронные (вызов в
`run_in_threadpool`, как остальные LLM-функции продукта). Исключения — только `EngineError` (ниже); сетевые сбои
поставщиков движок переводит в деградацию (аватар → голос → текст, модель → правила), а не в 500.

Назначение (FTT.4): **устная защита** письменных ответов теста — 2–4 вопроса по собственным развёрнутым ответам кандидата и
темам задания, итог «подтверждено устно / есть расхождения / мало данных» с цитатами, сверенными кодом. **Грейд не меняется**
— это сигнал доверия для работодателя. Второй режим — **ИИ-интервью** по навыкам потребности, которые тест не подтвердил.

```python
from app.modules.interview import engine
from app.modules.interview.engine.schemas import *
```

## 1. Схемы (`engine/schemas.py`)

```python
Mode    = Literal["defense", "interview"]
Channel = Literal["avatar", "voice", "text"]

class TaskContext(BaseModel):            # задание теста с развёрнутым ответом кандидата (режим defense)
    id: str                              # id задания в продукте
    kind: str | None = None              # open_answer | open_book_3step | predict_output | …
    title: str = ""                      # короткое название
    prompt: str | None = None            # текст задания (без эталона!)
    topics: list[str] = []               # ключевые темы, которые нужно подтвердить устно (≤ 8)
    answer: str                          # развёрнутый ответ кандидата как написал (≤ 6000 знаков)
    score: float | None = None           # доля баллов за задание 0–1 (для выбора, что защищать)
    integrity_flags: list[str] = []      # признаки целостности из продукта: paste | fast_text | ai_mark | injection | tab_switch …

class SkillContext(BaseModel):           # навык потребности, не подтверждённый тестом (режим interview)
    name: str
    why: str | None = None               # почему не подтверждён («в тесте нет заданий по экспериментам»)
    level: str | None = None             # нужный уровень словами

class DefenseContext(BaseModel):
    role: str | None = None              # направление/роль теста
    grade: str | None = None             # заявленный грейд (строкой); движок его НЕ меняет
    tasks: list[TaskContext]             # 1–6; защищаются только с answer ≥ 120 знаков

class InterviewContext(BaseModel):
    need_title: str
    need_summary: str | None = None      # что можно рассказать кандидату о позиции
    confirmed_skills: list[str] = []     # подтверждено тестом — об этом НЕ спрашиваем
    unconfirmed_skills: list[SkillContext]   # 1–8
    format_questions: list[str] = []     # вопросы о формате (один, если останется время)

class SessionSpec(BaseModel):            # параметры сессии; задаёт модуль interview при создании
    mode: Mode
    candidate_name: str                  # как обращаться (1–60 знаков, без фамилии)
    duration_min: int                    # defense 3–5 (по умолчанию 4); interview 5–15 (10) — engine.normalize_spec() подрежет
    max_questions: int                   # defense 2–4 (3); interview 3–8 (6)
    jury: bool = False                   # режим жюри: ≤ 5 мин, аватар только при INTERVIEW_JURY_AVATAR=1
    context: DefenseContext | InterviewContext
    started_at: datetime | None = None   # момент первой реплики кандидата (ставит движок в next_turn, модуль сохраняет)

class PlanItem(BaseModel):
    k: int                               # номер вопроса с 1
    task_id: str | None                  # defense
    skill: str | None                    # interview
    title: str
    angle: str                           # под каким углом спрашиваем («почему именно так», «что пойдёт не так» …)

class Utterance(BaseModel):
    who: Literal["interviewer", "candidate"]
    text: str                            # чистый текст (без служебных меток)
    at: datetime
    n: int | None = None                 # номер реплики кандидата с 1 (для цитат)
    channel: Channel | None = None
    kind: Literal["opening", "question", "repeat", "closing"] | None = None   # только у ведущего
    k: int | None = None                 # к какому пункту плана относился вопрос

class Transcript(BaseModel):
    items: list[Utterance] = []

class TurnInput(BaseModel):
    spec: SessionSpec
    transcript: Transcript
    candidate_text: str | None = None    # ответ кандидата (набранный или распознанный); None — первая реплика ведущего
    channel: Channel = "text"
    repeat: bool = False                 # кандидат просит повторить / ответ ведущего не дошёл — переформулировать последний вопрос
    now: datetime | None = None          # для тестов

class TurnOutput(BaseModel):
    text: str                            # что говорит ведущий (чистый текст для озвучки и показа)
    kind: Literal["opening", "question", "repeat", "closing"]
    k: int | None                        # пункт плана
    finished: bool                       # True — разговор окончен (прощание); модуль запускает evaluate()
    transcript: Transcript               # обновлённая (с ответом кандидата и репликой ведущего)
    started_at: datetime | None          # модуль сохраняет в сессию
    source: Literal["llm", "rules", "stub"]   # кто сформулировал реплику
    llm: dict | None = None              # provider/model/latency_ms/fallback (из LLMResult.info()) — для /api/meta и журнала
    cost_usd: float = 0.0                # стоимость этого хода (модель, точная цена OpenRouter, если известна)

class Quote(BaseModel):
    n: int                               # номер реплики кандидата
    text: str                            # дословный кусок (после нормализации содержится в реплике n)

class QuestionVerdict(BaseModel):
    k: int
    task_id: str | None
    skill: str | None
    question: str                        # текст вопроса ведущего
    answer_excerpt: str                  # ≤ 400 знаков ответа кандидата
    level: str                           # defense: confirmed | partial | discrepancy | no_data ; interview: strong | medium | weak | no_data
    level_label: str                     # по-русски
    quotes: list[Quote]                  # только сверенные кодом
    reasoning: str
    lowered: bool = False                # уровень снижен проверкой: цитаты модели не нашлись в расшифровке

class Verdict(BaseModel):
    verdict: str                         # defense: confirmed | discrepancies | insufficient ; interview: strong | medium | weak | insufficient
    verdict_label: str                   # «подтверждено устно» / «есть расхождения» / «мало данных» / …
    score: int | None                    # 0–100; None при insufficient
    summary: str                         # 2–4 предложения для карточки
    questions: list[QuestionVerdict]
    flags: list[str]                     # расхождения/риски с цитатами внутри текста (≤ 6)
    coverage: int                        # % вопросов с данными
    removed_quotes: int                  # сколько цитат модели не прошло сверку
    source: Literal["llm", "rules", "stub"]
    llm: dict | None = None              # по проходам: analyst/skeptic (provider, model, latency_ms)
    cost_usd: float = 0.0
    raw: dict | None = None              # сырые ответы аналитика и скептика (хранить работодателю не обязательно; для разбора)

class AudioOut(BaseModel):               # синтез речи
    data: bytes                          # аудио
    mime: str                            # "audio/mpeg" | "audio/pcm" (s16le)
    format: Literal["mp3", "pcm_16000"]  # pcm — s16le моно 16 кГц, формат потока звука аватара Anam
    sample_rate: int | None              # 16000 для pcm, None для mp3
    chars: int
    cost_usd: float
    stub: bool = False                   # заглушка: mp3 — data пустая (клиент показывает текст), pcm — тишина нужной длины

class Transcription(BaseModel):          # распознавание
    text: str
    seconds: float
    cost_usd: float
    stub: bool = False

class AvatarToken(BaseModel):
    session_token: str
    max_seconds: int
    ice_servers: list[dict] | None       # TURN/STUN для Anam SDK (по IP), None — серверы поставщика
    relay_only: bool                     # только через наш TURN (INTERVIEW_TURN_ONLY=1)
    persona_name: str                    # «Интервьюер»

class Cost(BaseModel):                   # агрегат для ответа работодателю/жюри — считает модуль из записанных долей
    usd: float; llm_usd: float = 0; tts_usd: float = 0; stt_usd: float = 0; avatar_usd: float = 0; estimated: bool = True
```

## 2. Функции (`engine/__init__.py` реэкспортирует)

| Функция | Что делает | Без ключей / сбой |
|---|---|---|
| `normalize_spec(spec) -> SessionSpec` | Подрезает длительность и число вопросов в пределы режима, жюри ≤ 5 мин; отбрасывает задания с answer < 120 знаков; `EngineError("insufficient_context")`, если защищать нечего | чисто |
| `plan(spec) -> list[PlanItem]` | План вопросов: задания с признаками целостности первыми, затем по длине ответа; при нехватке заданий — повторный заход под другим углом. Детерминирован | чисто |
| `next_turn(TurnInput) -> TurnOutput` | Добавляет ответ кандидата (если есть) в расшифровку, формулирует реплику ведущего (модель `INTERVIEW_MODEL_TURN`, по умолчанию Sonnet; промт свой), решает, закончен ли разговор (вопросов ≥ max или время ≥ duration → прощание) | модель недоступна → **правила** (вопрос из шаблона по теме и углу плана); заглушка — то же детерминированно |
| `evaluate(spec, transcript) -> Verdict` | Аналитик (модель `INTERVIEW_MODEL_JUDGE`, по умолчанию Fable 5.1) → скептик → **сборка кодом** (замечания скептика применяются детерминированно) → **сверка цитат кодом** → уровни → балл → вердикт | модель недоступна → правила (уровень по длине и пересечению слов с письменным ответом), `source="rules"`; мало данных → `insufficient` без вызова модели |
| `verify_quotes(quotes, transcript) -> tuple[list[Quote], int]` | Чистая сверка: цитата должна (после нормализации регистра/ё/пунктуации) содержаться в реплике `n`, иначе ищется в любой; короче 8 знаков — отбрасывается. Возвращает оставшиеся и число убранных | чисто |
| `verdict_from_levels(mode, levels, answers, chars) -> tuple[str, int \| None, str]` | Чистая таблица вердикта (раздел 3) | чисто |
| `tts(text, fmt="mp3") -> AudioOut` | ElevenLabs через ретранслятор (`providers/tts.py`), `fmt` = `mp3` (канал «голос») или `pcm_16000` (канал «аватар»); голос `ELEVENLABS_VOICE_ID` — **стоковый голос поставщика**, текст обрезается до 1200 знаков | нет ключа → `stub=True` (mp3: `data=b""`, клиент → текст); ошибка поставщика → `EngineError("bad_request", status=503)` |
| `stt(audio: bytes, mime="audio/webm", *, stub_text=None) -> Transcription` | Deepgram `nova-3`, ru (предзаписанный кусок до 6 МБ, «нажми и говори») через ретранслятор | нет ключа → `stub=True`, `text=stub_text or ""`; ошибка → `EngineError("stt_unavailable")` (модуль 503, клиент → текст) |
| `avatar_token(persona_name=None) -> AvatarToken` | **Только при `INTERVIEW_AVATAR_ENABLED=1`** (по умолчанию выключено — решение владельца 10.10, регламент п. 5.11: лицо стокового аватара поставщика в сдаче не показываем; без флага — `EngineError("avatar_unavailable")`, каналы — голос и текст). Токен сессии Anam (**стоковый аватар** `ANAM_AVATAR_ID`, модель `cara-4`, режим передачи звука — реплики озвучивает наш `tts(..., "pcm_16000")`, имя `INTERVIEWER_NAME`, плашка поставщика «ИИ-аватар» включена) через ретранслятор; `max_seconds` = `ANAM_MAX_SESSION_S`; `ice_servers` — наш TURN по IP с временными учётными данными (coturn use-auth-secret, 1 ч), `None` — ICE поставщика | нет ключа/ID или ошибка/сеть → `EngineError("avatar_unavailable")` (модуль 503, клиент → голос) |
| `check_limits(jury, sandbox_sessions_last_hour, spent_today_usd) -> None` | Лимиты (раздел 4), данные даёт модуль из своей БД | бросает `EngineError("jury_limit" \| "daily_cap", retry_after=…)` |
| `estimate_cost(kind, qty) -> float` | Ставки: `INTERVIEW_PRICE_TTS_1000`, `INTERVIEW_PRICE_STT_MIN`, `INTERVIEW_PRICE_AVATAR_MIN` | чисто |
| `status() -> dict` | Для `/api/interview/status` и `/api/meta`: `{"stub", "channels": {"text","voice","stt","avatar"}, "avatar_enabled", "models": {"turn","judge"}, "relay", "turn_ice", "interviewer_name", "limits", "daily_cap_usd", "label": "модель, не люди"}` — без секретов | чисто |
| `is_stub() -> bool` | `INTERVIEW_STUB=1` **или** нет ключа модели: реплики и оценка детерминированы, поставщики не вызываются | — |

`EngineError(code: str, message: str, *, status: int = 400, retry_after: int | None = None)` — коды: `insufficient_context` (422),
`bad_request` (400), `jury_limit` (429), `daily_cap` (429), `stt_unavailable` (503), `avatar_unavailable` (503), `finished` (409).

### Порядок вызовов в модуле (Я15)

1. Создание: `spec = normalize_spec(SessionSpec(...))`; `check_limits(...)`; сохранить spec и пустой `Transcript`.
2. Первая реплика: `out = next_turn(TurnInput(spec, transcript, candidate_text=None, channel=…))` → сохранить
   `out.transcript`, `out.started_at`; отдать клиенту `out.text` (+ `tts(out.text)` при голосе/аватаре).
3. Каждый ответ: текст из поля или `stt(audio)` → `next_turn(..., candidate_text=text)` → если `out.finished` →
   статус `finished` и в фоне `evaluate(spec, transcript)` → статус `evaluated`, сохранить `Verdict`.
4. «Повторить»: `next_turn(..., candidate_text=None, repeat=True)`.
5. Кандидат завершил сам / срок ссылки вышел: `evaluate()` того, что есть (при < 2 ответов — `insufficient`).

Модуль не должен показывать кандидату расшифровку и вердикт — только работодателю/эксперту. Расшифровка хранится без
видео и звука (аудио куски не сохраняются после `stt`).

## 3. Вердикт защиты (детерминированная таблица кода)

Уровни вопросов: `confirmed`=100, `partial`=60, `discrepancy`=10 баллов; `no_data` не считается. Балл — среднее по вопросам с
данными. Мало данных: ответов кандидата < 2 **или** суммарно < 150 знаков **или** ни одного вопроса с данными.

| verdict | когда | verdict_label |
|---|---|---|
| `confirmed` | нет `discrepancy`, балл ≥ 70 | подтверждено устно |
| `discrepancies` | есть `discrepancy` или балл < 50 | есть расхождения |
| `insufficient` | мало данных, либо 50 ≤ балл < 70 без `discrepancy` | мало данных |

Уровень `confirmed`/`partial` без сверенной цитаты → `no_data` (`lowered=True`); `discrepancy` без цитаты → `partial`
(`lowered=True`): обвинять без доказательства нельзя. Режим interview: `strong`=100, `medium`=60, `weak`=25; вердикт
`strong` ≥ 70, `medium` ≥ 45, иначе `weak`; `insufficient` — как выше.

## 4. Лимиты и стоимость

* Жюри: ≤ 1 сессия на песочницу в час и одна идущая (`jury_limit`, `retry_after`); длительность ≤ 5 мин; аватар — только при
  `INTERVIEW_JURY_AVATAR=1`.
* Дневной потолок `INTERVIEW_DAILY_CAP_USD` (по умолчанию 15): `spent_today_usd ≥ cap` → `daily_cap`; идущие сессии доводятся.
* Модель — точная цена OpenRouter (`usage.cost`, если ретранслятор/провайдер вернул), иначе 0 с `estimated`; TTS/STT/аватар —
  оценка по ставкам.

## 5. Переменные окружения движка (`engine/settings.py`, свой `InterviewSettings`, ничего в `app/core/config.py`)

`INTERVIEW_STUB`, `INTERVIEW_AVATAR_ENABLED` (по умолчанию выключено), `INTERVIEW_MODEL_TURN` (anthropic/claude-sonnet-4.6), `INTERVIEW_MODEL_JUDGE` (anthropic/claude-fable-5.1),
`INTERVIEW_RELAY_URL` (пусто — `LLM_RELAY_URL`), `INTERVIEW_RELAY_TOKEN` (пусто — `LLM_RELAY_TOKEN`), `LLM_RELAY_CA_FILE`
(общий закреплённый CA), `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`, `DEEPGRAM_API_KEY`, `ANAM_API_KEY`,
`ANAM_AVATAR_ID`, `ANAM_PERSONA_ID` (для учёта), `ANAM_MAX_SESSION_S` (600), `INTERVIEW_TURN_TIMEOUT_S` (25),
`INTERVIEW_JUDGE_TIMEOUT_S` (90), `INTERVIEW_TURN_URLS`, `INTERVIEW_TURN_SECRET`, `INTERVIEW_TURN_ONLY`,
`INTERVIEW_JURY_AVATAR`, `INTERVIEW_DAILY_CAP_USD`, `INTERVIEW_PRICE_TTS_1000`, `INTERVIEW_PRICE_STT_MIN`,
`INTERVIEW_PRICE_AVATAR_MIN`, `INTERVIEWER_NAME` («Интервьюер»). Флаг продукта `INTERVIEW_ENABLED` — у модуля (Я15).
Ключи на стенде — `secrets/interview.env` (env_file у `api`, см. `engine/DEPLOY.md`).

## 6. Заглушка и тесты

`is_stub()` — реплики ведущего из шаблонов по плану (приветствие по имени + вопрос 1 … прощание), оценка — правила
(`source="stub"`), поставщики не вызываются, `tts` отдаёт `stub=True`. Для e2e продукта в заглушке подойдут любые
тексты ответов; «честный» ответ в правилах — ≥ 120 знаков, ≥ 20 % общих значимых слов (по основам) с письменным ответом,
не почти дословный (< 60 % при < 200 знаках) и без общих слов («в целом главное», «наверное», «подробно не скажу») →
`confirmed`; «не помню / не знаю» в коротком ответе → `discrepancy`. Готовые реплики трёх ролей — `tools/interview_autocheck/personas.py` (SCRIPTED).
Тесты движка — `tests/test_interview_engine.py` (чистые функции, заглушка, сверка цитат, таблица вердикта, адаптеры с
подменой HTTP). Автопроверка на модельных кандидатах — `tools/interview_autocheck/` (модель, не люди).

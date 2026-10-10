# Движок ИИ-интервьюера — развёртывание (инструкция для штаба; серверы для исполнителей — только чтение)

## 1. Переменные окружения (`/opt/spectrek_fsp/secrets/interview.env` на «Москве»)

Файл подключается в `docker-compose.yml` как необязательный `env_file` сервиса `api` (см. раздел 2). Без него движок
работает в заглушке: детерминированные реплики и оценка по правилам, поставщики не вызываются, канал — только текст.

| Переменная | Значение / смысл |
|---|---|
| `INTERVIEW_ENABLED` | флаг модуля (Я15), по умолчанию выключено |
| `INTERVIEW_STUB` | `1` — принудительная заглушка (CI, демо без ключей) |
| `INTERVIEWER_NAME` | имя персонажа, по умолчанию «Интервьюер» |
| `INTERVIEW_MODEL_TURN` | модель реплик, по умолчанию `anthropic/claude-sonnet-4.6` (через OpenRouter и ретранслятор, как остальной backend) |
| `INTERVIEW_MODEL_JUDGE` | модель оценки (аналитик и скептик), по умолчанию `anthropic/claude-fable-5.1` |
| `INTERVIEW_TURN_TIMEOUT_S`, `INTERVIEW_JUDGE_TIMEOUT_S` | тайм-ауты модели: 25 с на реплику, 90 с на оценку |
| `INTERVIEW_RELAY_URL` | корень ретранслятора, напр. `https://<мадрид>:18743`; пусто — берётся `LLM_RELAY_URL` без хвоста `/api/v1` |
| `INTERVIEW_RELAY_TOKEN` | пусто — берётся `LLM_RELAY_TOKEN`; CA — общий `LLM_RELAY_CA_FILE` / `LLM_RELAY_CA_PEM_B64` |
| `ELEVENLABS_API_KEY` | ключ ElevenLabs (у штаба в `.private/interview.env`) |
| `ELEVENLABS_VOICE_ID` | `sRk0zCqhS2Cmv0bzx5wA` — стоковый голос библиотеки ElevenLabs «Felix — Calm, Clear and Friendly» (ru, мужской, спокойный); добавлен в аккаунт 10.10.2026 через API `POST /v1/voices/add` |
| `ELEVENLABS_MODEL` | `eleven_multilingual_v2` (по умолчанию) |
| `DEEPGRAM_API_KEY` | ключ Deepgram; модель `nova-3`, язык `ru`; режим «нажми и говори» — целый фрагмент за запрос |
| `INTERVIEW_AVATAR_ENABLED` | канал «аватар» (Anam). **По умолчанию выключен и в сдаче не включается** — решение владельца 10.10 (регламент п. 5.11: изображения третьих лиц). Без флага `avatar_token` отвечает `avatar_unavailable`, в `status()` `channels.avatar=false`; каналы — голос и текст, экран кандидата рисует собственную анимацию (Я15) |
| `ANAM_API_KEY` | ключ Anam (нужен только при `INTERVIEW_AVATAR_ENABLED=1`) |
| `ANAM_AVATAR_ID` | `19d18eb0-5346-4d50-a77f-26b3723ed79d` — стоковый образ поставщика «Richard (table)», модель `cara-4`, режим передачи звука (`enableAudioPassthrough`) |
| `ANAM_PERSONA_ID` | `25952956-4d5e-41ba-b0bc-54c11a971f6b` — персона «Интервьюер», создана 10.10.2026 10:37 UTC через `POST /v1/personas` (стоковый образ Richard + стоковый голос «Richard (ru)»); для учёта — в сессии используется `ANAM_AVATAR_ID` |
| `ANAM_MAX_SESSION_S` | предел сессии аватара, по умолчанию 600 |
| `INTERVIEW_TURN_URLS` | свой STUN/TURN по IP через запятую (`stun:IP:3478,turn:IP:3478?transport=udp,turns:IP:5349`); пусто — ICE поставщика |
| `INTERVIEW_TURN_SECRET` | общий секрет coturn (`use-auth-secret`); временные учётные данные выдаёт движок |
| `INTERVIEW_TURN_ONLY` | `1` — клиенту передать `iceTransportPolicy: relay` |
| `INTERVIEW_JURY_AVATAR` | `1` — разрешить аватар в режиме жюри (иначе жюри — голос и текст) |
| `INTERVIEW_DAILY_CAP_USD` | дневной потолок расходов, по умолчанию 15 |
| `INTERVIEW_PRICE_TTS_1000`, `INTERVIEW_PRICE_STT_MIN`, `INTERVIEW_PRICE_AVATAR_MIN` | ставки для оценки стоимости (0.15 / 0.0077 / 0.15 USD) |

Старые образы и голоса в аккаунтах поставщиков (созданные до 05.10) не используются: выбраны стоковые ресурсы
поставщиков, персона и голос добавлены 10.10.2026.

## 2. docker-compose

В `services.api.env_file` добавлено (в этой ветке):

```yaml
      # ИИ-интервьюер (backend/app/modules/interview/engine/DEPLOY.md): ключи ElevenLabs/Deepgram/Anam, ID стокового
      # аватара и голоса, ретранслятор. Нет файла — движок в заглушке (текст, правила), поставщики не вызываются.
      - path: ${INTERVIEW_ENV_FILE:-./secrets/interview.env}
        required: false
```

## 3. Ретранслятор

Обновить `/opt/fsp_relay/relay.py` на «Мадриде» файлом `infra/relay/relay.py` (инструкция и проверка —
`infra/relay/README.md`). До обновления движок через ретранслятор получит 404 на хосты поставщиков и уйдёт в
деградацию: аватар → голос → текст (ошибки `avatar_unavailable` / `stt_unavailable`, озвучка — 503).

## 4. Проверка после развёртывания

- `GET /api/interview/status` (Я15): `stub=false`, `channels.voice/stt=true`, `channels.avatar=false` (флаг выключен),
  `relay=true`, ключей в ответе нет.
- Журнал api: строки `interview turn` / `interview evaluate` без текста реплик.
- Журнал ретранслятора: `POST api.elevenlabs.io/... 200`, `POST api.deepgram.com/v1/listen 200`,
  (`POST api.anam.ai/v1/auth/session-token` — только если флаг аватара включён).

## 5. Что проверено 10.10.2026 из песочницы

- Напрямую и через локальный экземпляр нового ретранслятора: ElevenLabs (`pcm_16000`, `mp3_22050_32`), Deepgram
  (`nova-3`, ru — расшифровка озвученной реплики совпала с текстом дословно), Anam (`session-token` в режиме передачи
  звука, `showAIAvatarDisclosure`), OpenRouter потоком по прежнему пути.
- Выбор региона Anam (`sessionOptions.region`) для организации недоступен (403) — не передаётся.

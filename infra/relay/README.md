# Ретранслятор зарубежных API («Мадрид») — версия 2 для ИИ-интервьюера

Файл `relay.py` — замена `/opt/fsp_relay/relay.py` на сервере «Мадрид» (написан 10.10.2026, только стандартная
библиотека Python 3.11+). Прежнее поведение сохранено: запросы без заголовка `X-Relay-Host` с путём `/api/v1/...`
уходят на OpenRouter — LLM-клиент backend (`LLM_RELAY_URL=https://<мадрид>:18743/api/v1`) работает без изменений.

Новое:
- заголовок `X-Relay-Host` — пересылка на любой хост из белого списка `RELAY_HOSTS`
  (по умолчанию `openrouter.ai,api.elevenlabs.io,api.deepgram.com,api.anam.ai`); чужой хост — 404;
- бинарные тела (записи речи) до `RELAY_MAX_BODY` (8 МБ), ответ — потоком кусками по 64 КБ (SSE проходит без буферизации);
- пересылаются только заголовки `Authorization`, `Content-Type`, `Accept`, `xi-api-key`, `X-Title`, `HTTP-Referer`,
  `X-Request-Id`; ключи поставщиков хранятся на «Москве» и идут от клиента, у ретранслятора их нет;
- журнал — метод, хост, путь без строки запроса, статус, длительность; тел и заголовков в журнале нет.

Проверка (локально, самоподписанный сертификат, 10.10.2026): движок через этот ретранслятор получил озвучку ElevenLabs,
расшифровку Deepgram, сеансовый токен Anam и потоковый ответ OpenRouter по прежнему пути `/api/v1/chat/completions`.

## Установка на «Мадриде» (руками; серверы для исполнителей — только чтение)

```bash
sudo cp /opt/fsp_relay/relay.py /opt/fsp_relay/relay.py.bak-$(date +%F)
sudo cp infra/relay/relay.py /opt/fsp_relay/relay.py
sudo systemctl edit fsp-relay      # drop-in, при необходимости:
#   [Service]
#   Environment=RELAY_HOSTS=openrouter.ai,api.elevenlabs.io,api.deepgram.com,api.anam.ai
#   Environment=RELAY_ALLOWED_IPS=198.51.100.1
#   Environment=RELAY_MAX_BODY=8388608
sudo systemctl restart fsp-relay && systemctl status fsp-relay --no-pager
```

Юнит `fsp-relay` (DynamicUser, `LoadCredential=token:…`, `cert:…`, `key:…`) менять не нужно: файл читает те же
учётные данные из `$CREDENTIALS_DIRECTORY`. Переменные `RELAY_PORT`, `RELAY_ALLOWED_IPS`, `RELAY_HOSTS`,
`RELAY_MAX_BODY`, `RELAY_UPSTREAM_TIMEOUT`, `RELAY_LEGACY_HOST`, `RELAY_LEGACY_PREFIX` — необязательные.

Проверка с «Москвы» (токен — из `secrets/llm_relay.env`, не печатать):

```bash
curl -s --cacert /opt/spectrek_fsp/secrets/relay_ca.pem -H "X-Relay-Token: $LLM_RELAY_TOKEN" \
  -H "X-Relay-Host: api.anam.ai" -o /dev/null -w "%{http_code}\n" https://<мадрид>:18743/v1/avatars   # 401 от Anam = путь открыт
curl -s --cacert /opt/spectrek_fsp/secrets/relay_ca.pem -H "X-Relay-Token: $LLM_RELAY_TOKEN" \
  -H "X-Relay-Host: example.com" -o /dev/null -w "%{http_code}\n" https://<мадрид>:18743/v1/x        # 404 — хост вне списка
```

Локальная проверка файла без серверов: `openssl req -x509 -newkey rsa:2048 -nodes -keyout key -out cert -subj /CN=localhost`,
файл `token`, затем `CREDENTIALS_DIRECTORY=<каталог> RELAY_PORT=18799 RELAY_ALLOWED_IPS=127.0.0.1 python3 infra/relay/relay.py`.

Откат: вернуть `relay.py.bak-*` и перезапустить юнит.

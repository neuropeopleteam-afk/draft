# «Драфт» для Android и RuStore

Пакет `ru.fspdraft.app` (версия `1.2.0`, `versionCode 3`, `minSdk 24`, `targetSdk 36`) — официальный Android-пакет для RuStore, собранный поверх веб-приложения `https://fsp-draft.ru/?source=twa` с поддержкой 4 ярлыков разделов («Подборка», «Мой грейд», «Приглашения», «Спрос ФСП»), системных уведомлений и прямых ссылок `https://fsp-draft.ru/*`.

Готовый подписанный APK лежит в `frontend/public/app/draft-rustore.apk` (1,22 МБ, SHA-256 `08652a136781deceb8b0f949c3f00e15d6dc24daf143c36e1d8bb1187b3d734c`), метаданные — в `frontend/public/app/rustore.json`, комплект материалов для модерации RuStore — в `mobile/rustore/store/`, пошаговая инструкция публикации для владельца — в `mobile/RUSTORE_PUBLISH.md`.

## Сборка и подпись на сервере «Москва» (в одноразовом контейнере, ключ `:ro`)

```bash
docker run --rm --user 0 --memory 512m --cpus 1 \
  -v /opt/spectrek_fsp/work/ag_a7:/w \
  -v /opt/spectrek_fsp/secrets/rustore:/ks:ro \
  spectrek_fsp-api:latest \
  bash -c 'export JAVA_HOME=/w/sdk/jdk PATH=/w/sdk/jdk/bin:/w/sdk/android/build-tools/35.0.0:$PATH;
  apksigner sign --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
    --ks /ks/draft-upload.keystore --ks-key-alias draft --ks-pass file:/ks/ks_pw.txt \
    --out /w/draft-rustore.apk /w/aligned.apk &&
  apksigner verify --min-sdk-version 21 --verbose --print-certs /w/draft-rustore.apk'
```

Ключ загрузки и пароль хранятся на сервере в `/opt/spectrek_fsp/secrets/rustore/` (монтируются только для чтения, в репозиторий не попадают).
Отпечаток SHA-256 сертификата (`34:88:E3:44:72:DC:16:D1:1A:E4:9B:2C:00:D3:71:57:27:8F:E2:C4:5D:BF:E0:59:3B:43:01:47:A3:A2:40:A6`) опубликован в `/.well-known/assetlinks.json`.

# «Драфт» для Android и RuStore

Пакет `ru.fspdraft.app` (версия `1.1.0`, `versionCode 2`, `minSdk 24`, `targetSdk 36`) — официальный Android-пакет для RuStore, собранный поверх веб-приложения `https://fsp-draft.ru/?source=twa` с поддержкой ярлыков разделов («Подборка», «Мой грейд», «Приглашения»), системных уведомлений и прямых ссылок `https://fsp-draft.ru/*`.

Готовый подписанный APK лежит в `frontend/public/app/draft-rustore.apk` (1,22 МБ, SHA-256 `537cf272d53c3fea2b386a691a937b8c406747665577e593cd5d320a4c3b9ee9`), метаданные — в `frontend/public/app/rustore.json`, комплект материалов для модерации RuStore — в `mobile/rustore/store/`.

## Сборка (JDK 17, Android SDK: build-tools 35.0.0, platform 36)

```bash
cd mobile/rustore
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew assembleRelease --no-daemon
zipalign -p -f 4 app/build/outputs/apk/release/app-release-unsigned.apk aligned.apk
apksigner sign --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --ks draft-upload.keystore --ks-key-alias draft --out ../../frontend/public/app/draft-rustore.apk aligned.apk
apksigner verify --min-sdk-version 21 --verbose --print-certs ../../frontend/public/app/draft-rustore.apk
```

Ключ загрузки и пароль хранятся на сервере в `/opt/spectrek_fsp/secrets/rustore/` (в репозиторий не попадают).
Отпечаток SHA-256 сертификата (`34:88:E3:44:72:DC:16:D1:1A:E4:9B:2C:00:D3:71:57:27:8F:E2:C4:5D:BF:E0:59:3B:43:01:47:A3:A2:40:A6`) опубликован в `/.well-known/assetlinks.json`.

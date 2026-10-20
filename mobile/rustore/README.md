# «Драфт» для Android и RuStore (Trusted Web Activity)

Пакет `ru.fspdraft.app` — оболочка Trusted Web Activity над той же PWA (`https://fsp-draft.ru`), сгенерирована
Bubblewrap (`twa-manifest.json`), minSdk 24, targetSdk 36. Готовый подписанный APK лежит в
`frontend/public/app/draft-rustore.apk` и скачивается из окна «На телефон / RuStore» (шапка и главная страница).

Сборка (JDK 17, Android SDK: build-tools 35, platform 36):

```bash
cd mobile/rustore
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew assembleRelease
zipalign -p -f 4 app/build/outputs/apk/release/app-release-unsigned.apk aligned.apk
apksigner sign --ks draft-upload.keystore --ks-key-alias draft --out draft-rustore.apk aligned.apk
```

Ключ загрузки и пароль — на сервере в `/opt/spectrek_fsp/secrets/rustore/` (в репозиторий не попадают).
Отпечаток SHA-256 ключа опубликован в `/.well-known/assetlinks.json` — без него Android покажет адресную строку.
Публикация: RuStore Консоль → «Новое приложение» → загрузить APK, иконку 512×512 и скриншоты; модерация — на стороне RuStore.

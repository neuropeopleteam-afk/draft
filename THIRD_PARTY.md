# Сторонние компоненты и лицензии

Код проекта — MIT, см. [LICENSE](LICENSE). Ниже — всё стороннее, что используется проектом: библиотеки pip и npm (с транзитивными),
вендорные файлы в репозитории, шрифты и значки, образы Docker, данные. Файл создаётся скриптом `tools/publish/gen_third_party.py`
из установленных пакетов и `package-lock.json` (без сети); версии — как в файлах требований и lock-файлах.
Лицензии указаны по метаданным пакетов; где метаданные пусты — по исходникам пакета (таблица `LICENSE_OVERRIDES` в скрипте).
Копилефт: `psycopg` (LGPL-3.0) подключается как библиотека, без изменения кода; `pywebpush`/`py-vapid` и `certifi` — MPL-2.0 (файловый копилефт, правок нет).

## Python (pip)

### Бэкенд (рантайм)

Файлы требований: `backend/requirements.txt`. Пакетов: 76.

| Пакет | Версия | Лицензия | Связь |
|---|---|---|---|
| `aiohappyeyeballs` | 2.7.1 | PSF-2.0 | транзитивная |
| `aiohttp` | 3.14.4 | Apache-2.0 AND MIT | транзитивная |
| `aiosignal` | 1.4.0 | Apache-2.0 | транзитивная |
| `alembic` | 1.20.0 | MIT | прямая |
| `annotated-doc` | 0.0.5 | MIT | транзитивная |
| `annotated-types` | 0.8.0 | MIT | транзитивная |
| `anyio` | 4.15.1 | MIT | транзитивная |
| `argon2-cffi` | 25.1.0 | MIT | прямая |
| `argon2-cffi-bindings` | 26.1.0 | MIT | транзитивная |
| `attrs` | 26.1.0 | MIT | транзитивная |
| `boto3` | 1.43.108 | Apache-2.0 | прямая |
| `botocore` | 1.43.110 | Apache-2.0 | транзитивная |
| `certifi` | 2026.7.22 | MPL-2.0 | транзитивная |
| `cffi` | 2.1.1 | MIT-0 | транзитивная |
| `charset-normalizer` | 3.5.2 | MIT | транзитивная |
| `click` | 8.5.0 | BSD-3-Clause | транзитивная |
| `cryptography` | 50.0.2 | Apache-2.0 OR BSD-3-Clause | прямая |
| `DAWG-Python` | 0.7.2 | MIT | транзитивная |
| `dnspython` | 2.9.0 | ISC | транзитивная |
| `docopt` | 0.6.2 | MIT | транзитивная |
| `email-validator` | 2.3.0 | Unlicense | прямая |
| `fastapi` | 0.142.2 | MIT | прямая |
| `frozenlist` | 1.8.0 | Apache-2.0 | транзитивная |
| `h11` | 0.16.0 | MIT | транзитивная |
| `http_ece` | 1.2.1 | MIT | транзитивная |
| `httpcore` | 1.0.9 | BSD-3-Clause | транзитивная |
| `httptools` | 0.8.0 | MIT | транзитивная |
| `httpx` | 0.28.1 | BSD-3-Clause | прямая |
| `idna` | 3.20 | BSD-3-Clause | транзитивная |
| `intervaltree` | 3.2.1 | Apache-2.0 | транзитивная |
| `ipymarkup` | 0.9.0 | MIT | транзитивная |
| `jmespath` | 1.1.0 | MIT | транзитивная |
| `Mako` | 1.4.3 | MIT | транзитивная |
| `MarkupSafe` | 3.0.4 | BSD-3-Clause | транзитивная |
| `multidict` | 6.9.1 | Apache License 2.0 | транзитивная |
| `natasha` | 1.6.0 | MIT | прямая |
| `navec` | 0.10.0 | MIT | транзитивная |
| `numpy` | 2.1.3 | BSD-3-Clause | прямая |
| `opentelemetry-api` | 1.45.1 | Apache-2.0 | транзитивная |
| `pillow` | 12.3.0 | MIT-CMU | транзитивная |
| `propcache` | 0.5.4 | Apache-2.0 | транзитивная |
| `psycopg` | 3.3.6 | LGPL-3.0-only | прямая |
| `psycopg-binary` | 3.3.6 | LGPL-3.0-only | транзитивная |
| `py-vapid` | 1.9.4 | MPL-2.0 | транзитивная |
| `pycparser` | 3.1 | BSD-3-Clause | транзитивная |
| `pydantic` | 2.13.5 | MIT | прямая |
| `pydantic_core` | 2.46.5 | MIT | транзитивная |
| `pydantic-settings` | 2.15.0 | MIT | прямая |
| `PyJWT` | 2.15.1 | MIT | прямая |
| `pymorphy2` | 0.9.1 | MIT | транзитивная |
| `pymorphy2-dicts-ru` | 2.4.417127.4579844 | MIT | транзитивная |
| `pypdf` | 6.19.0 | BSD-3-Clause | прямая |
| `python-dateutil` | 2.9.0.post0 | Apache-2.0 / BSD-3-Clause | транзитивная |
| `python-dotenv` | 1.2.4 | BSD-3-Clause | транзитивная |
| `python-multipart` | 0.0.32 | Apache-2.0 | прямая |
| `pywebpush` | 2.5.0 | MPL-2.0 | прямая |
| `PyYAML` | 6.0.3 | MIT | прямая |
| `razdel` | 0.5.0 | MIT | транзитивная |
| `reportlab` | 5.0.1 | BSD-3-Clause | прямая |
| `requests` | 2.34.2 | Apache-2.0 | транзитивная |
| `s3transfer` | 0.19.2 | Apache-2.0 | транзитивная |
| `scipy` | 1.14.1 | BSD-3-Clause | прямая |
| `six` | 1.17.0 | MIT | транзитивная |
| `slovnet` | 0.6.0 | MIT | транзитивная |
| `sortedcontainers` | 2.4.0 | Apache-2.0 | транзитивная |
| `SQLAlchemy` | 2.1.3 | MIT | прямая |
| `starlette` | 1.7.0 | BSD-3-Clause | транзитивная |
| `typing_extensions` | 4.16.0 | PSF-2.0 | транзитивная |
| `typing-inspection` | 0.4.4 | MIT | транзитивная |
| `urllib3` | 2.8.0 | MIT | транзитивная |
| `uvicorn` | 0.54.0 | BSD-3-Clause | прямая |
| `uvloop` | 0.23.0 | Apache-2.0 / MIT | транзитивная |
| `watchfiles` | 1.3.0 | MIT | транзитивная |
| `websockets` | 17.2 | BSD-3-Clause | транзитивная |
| `yargy` | 0.16.0 | MIT | транзитивная |
| `yarl` | 1.25.1 | Apache-2.0 | транзитивная |

### Разработка и тесты бэкенда

Файлы требований: `backend/requirements-dev.txt`. Пакетов: 14.

| Пакет | Версия | Лицензия | Связь |
|---|---|---|---|
| `anyio` | 4.15.1 | MIT | транзитивная |
| `certifi` | 2026.7.22 | MPL-2.0 | транзитивная |
| `coverage` | 7.16.2 | Apache-2.0 | транзитивная |
| `h11` | 0.16.0 | MIT | транзитивная |
| `httpcore` | 1.0.9 | BSD-3-Clause | транзитивная |
| `httpx` | 0.28.1 | BSD-3-Clause | прямая |
| `idna` | 3.20 | BSD-3-Clause | транзитивная |
| `iniconfig` | 2.3.1 | MIT | транзитивная |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | транзитивная |
| `pluggy` | 1.6.0 | MIT | транзитивная |
| `Pygments` | 2.21.0 | BSD-2-Clause | транзитивная |
| `pytest` | 9.1.1 | MIT | прямая |
| `pytest-cov` | 7.1.0 | MIT | прямая |
| `typing_extensions` | 4.16.0 | PSF-2.0 | транзитивная |

### Банк заданий (`backend/assessment_bank`, ставится отдельно для проверки ключей)

Файлы требований: `backend/assessment_bank/BANK_requirements.txt`. Пакетов: 15.

| Пакет | Версия | Лицензия | Связь |
|---|---|---|---|
| `annotated-types` | 0.8.0 | MIT | транзитивная |
| `asgiref` | 3.12.1 | BSD-3-Clause | транзитивная |
| `Django` | 5.2.17 | BSD-3-Clause | прямая |
| `iniconfig` | 2.3.1 | MIT | транзитивная |
| `numpy` | 2.1.3 | BSD-3-Clause | прямая |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | транзитивная |
| `pluggy` | 1.6.0 | MIT | транзитивная |
| `pydantic` | 2.9.2 | MIT | прямая |
| `pydantic_core` | 2.23.4 | MIT | транзитивная |
| `Pygments` | 2.21.0 | BSD-2-Clause | транзитивная |
| `pytest` | 9.1.1 | MIT | прямая |
| `PyYAML` | 6.0.2 | MIT | прямая |
| `scipy` | 1.14.1 | BSD-3-Clause | прямая |
| `sqlparse` | 0.6.0 | BSD-3-Clause | транзитивная |
| `typing_extensions` | 4.16.0 | PSF-2.0 | транзитивная |

## npm

### Фронтенд (`frontend/package-lock.json`)

Всего пакетов: 187; в сборку попадают 9 (остальные — инструменты разработки).

**В сборке (production):**

| Пакет | Версия | Лицензия |
|---|---|---|
| `@fontsource/montserrat` | 5.3.0 | OFL-1.1 |
| `@remix-run/router` | 1.23.4 | MIT |
| `js-tokens` | 4.0.0 | MIT |
| `loose-envify` | 1.4.0 | MIT |
| `react` | 18.3.1 | MIT |
| `react-dom` | 18.3.1 | MIT |
| `react-router` | 6.30.6 | MIT |
| `react-router-dom` | 6.30.6 | MIT |
| `scheduler` | 0.23.2 | MIT |

**Только разработка и сборка:**

| Пакет | Версия | Лицензия |
|---|---|---|
| `@alloc/quick-lru` | 5.3.0 | MIT |
| `@babel/code-frame` | 7.29.7 | MIT |
| `@babel/compat-data` | 7.29.7 | MIT |
| `@babel/core` | 7.29.7 | MIT |
| `@babel/generator` | 7.29.8 | MIT |
| `@babel/helper-compilation-targets` | 7.29.7 | MIT |
| `@babel/helper-globals` | 7.29.7 | MIT |
| `@babel/helper-module-imports` | 7.29.7 | MIT |
| `@babel/helper-module-transforms` | 7.29.7 | MIT |
| `@babel/helper-plugin-utils` | 7.29.7 | MIT |
| `@babel/helper-string-parser` | 7.29.7 | MIT |
| `@babel/helper-validator-identifier` | 7.29.7 | MIT |
| `@babel/helper-validator-option` | 7.29.7 | MIT |
| `@babel/helpers` | 7.29.7 | MIT |
| `@babel/parser` | 7.29.9 | MIT |
| `@babel/plugin-transform-react-jsx-self` | 7.29.7 | MIT |
| `@babel/plugin-transform-react-jsx-source` | 7.29.7 | MIT |
| `@babel/template` | 7.29.7 | MIT |
| `@babel/traverse` | 7.29.8 | MIT |
| `@babel/types` | 7.29.8 | MIT |
| `@esbuild/aix-ppc64` | 0.21.5 | MIT |
| `@esbuild/android-arm` | 0.21.5 | MIT |
| `@esbuild/android-arm64` | 0.21.5 | MIT |
| `@esbuild/android-x64` | 0.21.5 | MIT |
| `@esbuild/darwin-arm64` | 0.21.5 | MIT |
| `@esbuild/darwin-x64` | 0.21.5 | MIT |
| `@esbuild/freebsd-arm64` | 0.21.5 | MIT |
| `@esbuild/freebsd-x64` | 0.21.5 | MIT |
| `@esbuild/linux-arm` | 0.21.5 | MIT |
| `@esbuild/linux-arm64` | 0.21.5 | MIT |
| `@esbuild/linux-ia32` | 0.21.5 | MIT |
| `@esbuild/linux-loong64` | 0.21.5 | MIT |
| `@esbuild/linux-mips64el` | 0.21.5 | MIT |
| `@esbuild/linux-ppc64` | 0.21.5 | MIT |
| `@esbuild/linux-riscv64` | 0.21.5 | MIT |
| `@esbuild/linux-s390x` | 0.21.5 | MIT |
| `@esbuild/linux-x64` | 0.21.5 | MIT |
| `@esbuild/netbsd-x64` | 0.21.5 | MIT |
| `@esbuild/openbsd-x64` | 0.21.5 | MIT |
| `@esbuild/sunos-x64` | 0.21.5 | MIT |
| `@esbuild/win32-arm64` | 0.21.5 | MIT |
| `@esbuild/win32-ia32` | 0.21.5 | MIT |
| `@esbuild/win32-x64` | 0.21.5 | MIT |
| `@jridgewell/gen-mapping` | 0.3.13 | MIT |
| `@jridgewell/remapping` | 2.3.5 | MIT |
| `@jridgewell/resolve-uri` | 3.1.2 | MIT |
| `@jridgewell/sourcemap-codec` | 1.6.0 | MIT |
| `@jridgewell/trace-mapping` | 0.3.31 | MIT |
| `@napi-rs/lzma-linux-x64-gnu` | 1.5.1 | MIT |
| `@nodelib/fs.scandir` | 2.1.5 | MIT |
| `@nodelib/fs.stat` | 2.0.5 | MIT |
| `@nodelib/fs.walk` | 1.2.8 | MIT |
| `@rolldown/pluginutils` | 1.0.0-beta.27 | MIT |
| `@rollup/rollup-android-arm-eabi` | 4.64.0 | MIT |
| `@rollup/rollup-android-arm64` | 4.64.0 | MIT |
| `@rollup/rollup-darwin-arm64` | 4.64.0 | MIT |
| `@rollup/rollup-darwin-x64` | 4.64.0 | MIT |
| `@rollup/rollup-freebsd-arm64` | 4.64.0 | MIT |
| `@rollup/rollup-freebsd-x64` | 4.64.0 | MIT |
| `@rollup/rollup-linux-arm-gnueabihf` | 4.64.0 | MIT |
| `@rollup/rollup-linux-arm-musleabihf` | 4.64.0 | MIT |
| `@rollup/rollup-linux-arm64-gnu` | 4.64.0 | MIT |
| `@rollup/rollup-linux-arm64-musl` | 4.64.0 | MIT |
| `@rollup/rollup-linux-loong64-gnu` | 4.64.0 | MIT |
| `@rollup/rollup-linux-loong64-musl` | 4.64.0 | MIT |
| `@rollup/rollup-linux-ppc64-gnu` | 4.64.0 | MIT |
| `@rollup/rollup-linux-ppc64-musl` | 4.64.0 | MIT |
| `@rollup/rollup-linux-riscv64-gnu` | 4.64.0 | MIT |
| `@rollup/rollup-linux-riscv64-musl` | 4.64.0 | MIT |
| `@rollup/rollup-linux-s390x-gnu` | 4.64.0 | MIT |
| `@rollup/rollup-linux-x64-gnu` | 4.64.0 | MIT |
| `@rollup/rollup-linux-x64-musl` | 4.64.0 | MIT |
| `@rollup/rollup-openbsd-x64` | 4.64.0 | MIT |
| `@rollup/rollup-openharmony-arm64` | 4.64.0 | MIT |
| `@rollup/rollup-win32-arm64-msvc` | 4.64.0 | MIT |
| `@rollup/rollup-win32-ia32-msvc` | 4.64.0 | MIT |
| `@rollup/rollup-win32-x64-gnu` | 4.64.0 | MIT |
| `@rollup/rollup-win32-x64-msvc` | 4.64.0 | MIT |
| `@types/babel__core` | 7.20.5 | MIT |
| `@types/babel__generator` | 7.27.0 | MIT |
| `@types/babel__template` | 7.4.4 | MIT |
| `@types/babel__traverse` | 7.28.0 | MIT |
| `@types/estree` | 1.0.9 | MIT |
| `@types/node` | 20.19.43 | MIT |
| `@types/prop-types` | 15.7.15 | MIT |
| `@types/react` | 18.3.31 | MIT |
| `@types/react-dom` | 18.3.7 | MIT |
| `@vitejs/plugin-react` | 4.7.0 | MIT |
| `any-promise` | 1.3.0 | MIT |
| `anymatch` | 3.1.3 | ISC |
| `arg` | 5.0.2 | MIT |
| `autoprefixer` | 10.6.1 | MIT |
| `baseline-browser-mapping` | 2.11.27 | Apache-2.0 |
| `binary-extensions` | 2.3.0 | MIT |
| `braces` | 3.0.3 | MIT |
| `browserslist` | 4.29.3 | MIT |
| `camelcase-css` | 2.0.1 | MIT |
| `caniuse-lite` | 1.0.30001814 | CC-BY-4.0 |
| `chokidar` | 3.6.0 | MIT |
| `glob-parent` | 5.1.2 | ISC |
| `commander` | 4.1.1 | MIT |
| `convert-source-map` | 2.0.0 | MIT |
| `cssesc` | 3.0.0 | MIT |
| `csstype` | 3.2.3 | MIT |
| `debug` | 4.4.3 | MIT |
| `didyoumean` | 1.2.2 | Apache-2.0 |
| `dlv` | 1.1.3 | MIT |
| `electron-to-chromium` | 1.5.444 | ISC |
| `es-errors` | 1.3.0 | MIT |
| `esbuild` | 0.21.5 | MIT |
| `escalade` | 3.2.0 | MIT |
| `fast-glob` | 3.3.3 | MIT |
| `glob-parent` | 5.1.2 | ISC |
| `fastq` | 1.20.3 | ISC |
| `fill-range` | 7.1.1 | MIT |
| `fraction.js` | 5.3.4 | MIT |
| `fsevents` | 2.3.3 | MIT |
| `function-bind` | 1.1.2 | MIT |
| `gensync` | 1.0.0-beta.2 | MIT |
| `glob-parent` | 6.0.2 | ISC |
| `hasown` | 2.0.4 | MIT |
| `is-binary-path` | 2.1.0 | MIT |
| `is-core-module` | 2.17.0 | MIT |
| `is-extglob` | 2.1.1 | MIT |
| `is-glob` | 4.0.3 | MIT |
| `is-number` | 7.0.0 | MIT |
| `jiti` | 1.21.7 | MIT |
| `jsesc` | 3.1.0 | MIT |
| `json5` | 2.2.3 | MIT |
| `lilconfig` | 3.1.3 | MIT |
| `lines-and-columns` | 1.2.4 | MIT |
| `lru-cache` | 5.1.1 | ISC |
| `merge2` | 1.4.1 | MIT |
| `micromatch` | 4.0.8 | MIT |
| `ms` | 2.1.3 | MIT |
| `mz` | 2.7.0 | MIT |
| `nanoid` | 3.3.20 | MIT |
| `node-releases` | 2.0.57 | MIT |
| `normalize-path` | 3.0.0 | MIT |
| `object-assign` | 4.1.1 | MIT |
| `object-hash` | 3.0.0 | MIT |
| `path-parse` | 1.0.7 | MIT |
| `picocolors` | 1.1.1 | ISC |
| `picomatch` | 2.3.2 | MIT |
| `pirates` | 4.0.7 | MIT |
| `postcss` | 8.5.29 | MIT |
| `postcss-import` | 15.1.0 | MIT |
| `postcss-js` | 4.1.0 | MIT |
| `postcss-load-config` | 6.0.1 | MIT |
| `postcss-nested` | 6.2.0 | MIT |
| `postcss-selector-parser` | 6.1.4 | MIT |
| `postcss-value-parser` | 4.2.0 | MIT |
| `queue-microtask` | 1.2.3 | MIT |
| `react-refresh` | 0.17.0 | MIT |
| `read-cache` | 1.0.2 | MIT |
| `readdirp` | 3.6.0 | MIT |
| `resolve` | 1.22.12 | MIT |
| `reusify` | 1.1.0 | MIT |
| `rollup` | 4.64.0 | MIT |
| `run-parallel` | 1.2.0 | MIT |
| `semver` | 6.3.1 | ISC |
| `source-map-js` | 1.2.2 | BSD-3-Clause |
| `sucrase` | 3.35.1 | MIT |
| `supports-preserve-symlinks-flag` | 1.0.0 | MIT |
| `tailwindcss` | 3.4.19 | MIT |
| `thenify` | 3.3.1 | MIT |
| `thenify-all` | 1.6.0 | MIT |
| `tinyglobby` | 0.2.17 | MIT |
| `fdir` | 6.5.0 | MIT |
| `picomatch` | 4.0.7 | MIT |
| `to-regex-range` | 5.0.1 | MIT |
| `ts-interface-checker` | 0.1.13 | Apache-2.0 |
| `typescript` | 5.9.3 | Apache-2.0 |
| `undici-types` | 6.21.0 | MIT |
| `update-browserslist-db` | 1.3.3 | MIT |
| `util-deprecate` | 1.0.2 | MIT |
| `vite` | 5.4.21 | MIT |
| `yallist` | 3.1.1 | ISC |

### Сквозные тесты (`e2e/package-lock.json`)

Всего пакетов: 6; в сборку попадают 0 (остальные — инструменты разработки).

**Только разработка и сборка:**

| Пакет | Версия | Лицензия |
|---|---|---|
| `@playwright/test` | 1.63.0 | Apache-2.0 |
| `@types/node` | 20.19.43 | MIT |
| `playwright` | 1.63.0 | Apache-2.0 |
| `playwright-core` | 1.63.0 | Apache-2.0 |
| `typescript` | 5.9.3 | Apache-2.0 |
| `undici-types` | 6.21.0 | MIT |

## Вендорные файлы в репозитории

| Что | Лицензия | Текст лицензии |
|---|---|---|
| Swagger UI, пакет swagger-ui-dist 5.33.1 (`backend/app/static/apidocs/swagger-ui-*`), вендорен, чтобы документация API не зависела от внешних CDN | Apache-2.0 | `backend/app/static/apidocs/LICENSE.swagger-ui` |
| ReDoc 2.5.4 (`backend/app/static/apidocs/redoc.standalone.js`) | MIT | `backend/app/static/apidocs/LICENSE.redoc` |
| MediaPipe Tasks Vision 1.1.0, wasm и js (`frontend/public/vendor/mediapipe/1.1.0/`) — детекция лица в тесте по согласию, работает в браузере, видео не отправляется | Apache-2.0 | `frontend/public/vendor/mediapipe/1.1.0/LICENSE` |
| Модель BlazeFace short range (`blaze_face_short_range.tflite`, там же) | Apache-2.0 (модель Google MediaPipe) | `frontend/public/vendor/mediapipe/1.1.0/LICENSE` |

## Шрифты и значки

| Что | Лицензия | Как используется |
|---|---|---|
| Montserrat | SIL Open Font License 1.1 | подключается как npm-пакет `@fontsource/montserrat`; файлы шрифтов в репозитории не лежат, попадают только в сборку `frontend/dist` |
| DejaVu Sans | Bitstream Vera License / Public Domain для правок DejaVu | ставится в образ API пакетом ОС `fonts-dejavu-core` для кириллицы в PDF-профиле; в репозитории не хранится |
| Иконки интерфейса и PWA (`frontend/public/icons/`, `favicon.svg`) и встроенные SVG-значки | MIT (авторские, часть проекта) | нарисованы в проекте; чужих наборов иконок (Font Awesome, Material, Lucide и т. п.) нет |

## Образы Docker и модели

| Что | Лицензия | Где используется |
|---|---|---|
| `python:3.12-slim` | PSF-2.0 (Python); Debian — набор лицензий пакетов | образ API (`backend/Dockerfile`) |
| `node:20-alpine` | MIT (Node.js); Alpine — набор лицензий пакетов | только сборка фронтенда (`frontend/Dockerfile`) |
| `nginx:1.27-alpine` | BSD-2-Clause | раздача фронтенда (`frontend/Dockerfile`) |
| `postgres:16-alpine` | PostgreSQL License | база данных (`docker-compose.yml`) |
| `quay.io/keycloak/keycloak:26.4.0` | Apache-2.0 | демо «ФСП ID», профиль `fsp-id` (`keycloak/Dockerfile`) |
| `ghcr.io/ggml-org/llama.cpp:server-b11515` | MIT | локальная открытая модель, профиль `llm-local` (по умолчанию выключен) |
| Qwen3.5-9B (GGUF, `unsloth/Qwen3.5-9B-GGUF:Q4_K_M`) | Apache-2.0 (по [карточке модели Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B); квантование GGUF — unsloth) | скачивается с Hugging Face только при `make llm-local`, в репозитории нет |

## Данные и материалы

| Что | Где | Права и оговорки |
|---|---|---|
| Калькулятор зарплат Хабр Карьеры: агрегаты (перцентили по специализациям) на 05.10.2026 | `docs/data_habr_salary_raw_20261005.json`, `docs/SALARY_SOURCES.md` | публичные агрегаты страницы калькулятора; источник и дата указаны; персональных данных нет |
| 50 публичных объявлений о вакансиях: дословные фрагменты, URL источника, дата сбора 07.10.2026, SHA-256 | `docs/realdata/vacancies_50.json`, тесты разбора потребности | права на тексты принадлежат авторам объявлений; используются только как проверочный корпус разбора; контактов нет; по запросу правообладателя будут удалены |
| Модельные кандидаты, работодатели, вакансии демо-стенда | `backend/app/modules/demo/`, `backend/app/modules/jury/seed.py` | синтетические, имена и почты вымышлены (`*@demo.invalid`); совпадения с реальными людьми случайны |
| Фотография лица для проверки камеры в e2e (`e2e/fixtures/webcam_face.jpg`, `webcam_face.y4m`) | `e2e/fixtures/` | сгенерирована нейросетью, лицо несуществующего человека; используется только в автотесте |
| Снимки экранов интерфейса в `docs/**/*.png` | `docs/` | собственные, сняты с демо-данными |
| Задания банка (`backend/assessment_bank/families`) | `backend/assessment_bank/` | авторские, генерируются параметрически; лицензия — `BANK_LICENSE` (MIT) |

## Как обновить

```bash
# из окружения бэкенда (pip install -r backend/requirements.txt -r backend/requirements-dev.txt)
python tools/publish/gen_third_party.py            # перезаписывает THIRD_PARTY.md
python tools/publish/gen_third_party.py --check    # код выхода 1, если файл устарел
```

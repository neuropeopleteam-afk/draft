# MediaPipe Tasks Vision 1.1.0 — локальная копия (без CDN)

Детектор лица для прокторинга с камерой по согласию (`src/proctor/`). Файлы раздаёт nginx фронтенда с нашего
домена; загружаются лениво — только когда кандидат нажал «Включить камеру» перед тестом. Кадры в сеть не уходят.

| Файл | Откуда | SHA-256 |
|---|---|---|
| vision_bundle.mjs | npm `@mediapipe/tasks-vision@1.1.0` (`vision_bundle.mjs`) | 9d5fc9ef74b22329cf9aa88dc543956d192b8c254210b187271614713eb5b10c |
| vision_wasm_internal.js | тот же пакет, `wasm/vision_wasm_internal.js` (сборка с SIMD) | 7c652617b5bef832f42878ce8c5f752b0724bca6054e4bc1013a37d4b1949723 |
| vision_wasm_internal.wasm | тот же пакет, `wasm/vision_wasm_internal.wasm` | 782eda3ec1f414fdb4f1d66a8b59093eb4d5ab437e06117796abf05962d68eef |
| blaze_face_short_range.tflite | https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite | b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f |

Лицензия — Apache-2.0 (файл LICENSE, https://github.com/google-ai-edge/mediapipe). Файлы не изменены.
Сборка без SIMD (`vision_wasm_nosimd_internal.*`, ещё 12 МБ) не включена: WebAssembly SIMD есть в Chrome 91+,
Firefox 89+, Safari 16.4+; в браузере без SIMD тест честно предлагается пройти без камеры.

Обновление: скачать пакет (`npm pack @mediapipe/tasks-vision@<версия>`), положить файлы в новый каталог
`vendor/mediapipe/<версия>/` и поменять `MP_BASE` в `src/proctor/detector.ts`.

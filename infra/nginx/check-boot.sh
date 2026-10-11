#!/usr/bin/env bash
# Я16: проверка раздачи интерфейса после выкладки (только чтение, curl): сжатые заранее файлы сборки с Content-Length,
# кэш файлов сборки — навсегда, index.html и sw.js — no-cache, нет файла сборки — 404 (не HTML), стартовый JS в бюджете.
#
#   bash infra/nginx/check-boot.sh https://fsp.neuropeople.pro         # базовая авторизация — из BASIC_USER/BASIC_PASSWORD
#   CURL_EXTRA="--socks5-hostname 127.0.0.1:1080" bash infra/nginx/check-boot.sh https://fsp.neuropeople.pro
#   bash infra/nginx/check-boot.sh http://127.0.0.1:8140               # контейнер web напрямую
#
# Код выхода — число проваленных проверок (0 — всё в порядке). Пароль в вывод не попадает.
set -uo pipefail
BASE=${1:-http://127.0.0.1:8140}; BASE=${BASE%/}
AUTH=()
[ -n "${BASIC_USER:-}" ] && [ -n "${BASIC_PASSWORD:-}" ] && AUTH=(-u "$BASIC_USER:$BASIC_PASSWORD")
# shellcheck disable=SC2206
EXTRA=(${CURL_EXTRA:-})
BUDGET=${BOOT_BUDGET_BYTES:-256000}   # стартовый JS (gzip на проводе), 250 КБ
fails=0
ok()   { printf 'ok    %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }
hdrs() { curl -s -o /dev/null -D - -m 30 "${EXTRA[@]}" "${AUTH[@]}" -H 'Accept-Encoding: gzip, br' "$BASE$1" | tr -d '\r'; }
hval() { grep -i "^$2:" <<<"$1" | head -1 | cut -d' ' -f2- ; }

html=$(curl -s -m 30 "${EXTRA[@]}" "${AUTH[@]}" "$BASE/")
[ -n "$html" ] || { bad "/ — пустой ответ"; exit 1; }
grep -q '__fspBoot' <<<"$html" && ok "/ — сторож загрузки в index.html" || bad "/ — нет сторожа загрузки (__fspBoot): выложена прежняя сборка?"
size=$(printf '%s' "$html" | wc -c)
[ "$size" -le 12288 ] && ok "index.html $size Б (≤ 12 КБ: доходит целиком даже при обрыве ~16 КБ)" || bad "index.html $size Б > 12 КБ"
grep -q 'src="/recover.js"' <<<"$html" && bad "index.html подключает блокирующий /recover.js" || ok "нет блокирующего /recover.js в <head>"

h=$(hdrs /)
[[ "$(hval "$h" Cache-Control)" == *no-cache* ]] && ok "/ Cache-Control: $(hval "$h" Cache-Control)" || bad "/ без no-cache: $(hval "$h" Cache-Control)"
h=$(hdrs /index.html)
[[ "$(hval "$h" Cache-Control)" == *no-cache* ]] && ok "/index.html no-cache" || bad "/index.html без no-cache"
h=$(hdrs /sw.js)
[[ "$(hval "$h" Cache-Control)" == *no-cache* ]] && ok "/sw.js no-cache" || bad "/sw.js без no-cache"

start=$(grep -oE '<(script type="module"[^>]*src|link rel="modulepreload"[^>]*href)="/assets/[^"]+\.js"' <<<"$html" | grep -oE '/assets/[^"]+\.js')
total=0
for a in $start; do
  h=$(hdrs "$a")
  code=$(head -1 <<<"$h" | cut -d' ' -f2); enc=$(hval "$h" Content-Encoding); len=$(hval "$h" Content-Length); cc=$(hval "$h" Cache-Control)
  [ "$code" = 200 ] || bad "$a → HTTP $code"
  [ "$enc" = gzip ] || [ "$enc" = br ] && ok "$a сжат ($enc)" || bad "$a без сжатия"
  [ -n "$len" ] && ok "$a Content-Length $len (сжат заранее, gzip_static)" || bad "$a без Content-Length (сжатие «на лету», chunked)"
  [[ "$cc" == *immutable* ]] && [ "$(grep -ci '^cache-control:' <<<"$h")" = 1 ] && ok "$a Cache-Control: $cc" || bad "$a Cache-Control: $(grep -i '^cache-control:' <<<"$h" | tr '\n' ' ')"
  # байты на проводе: Content-Length, а без него — фактически скачанное (сжатое) тело
  [ -n "$len" ] || len=$(curl -s -o /dev/null -m 60 "${EXTRA[@]}" "${AUTH[@]}" -H 'Accept-Encoding: gzip' -w '%{size_download}' "$BASE$a")
  total=$((total + ${len:-0}))
done
[ -n "$start" ] || bad "в index.html нет файлов сборки"
[ "$total" -gt 0 ] && [ "$total" -le "$BUDGET" ] && ok "стартовый JS на проводе $total Б (≤ $BUDGET)" || bad "стартовый JS на проводе $total Б (бюджет $BUDGET)"

h=$(hdrs /assets/no-such-file-boot-check.js)
code=$(head -1 <<<"$h" | cut -d' ' -f2); ct=$(hval "$h" Content-Type)
[ "$code" = 404 ] && ok "нет файла сборки → 404" || bad "нет файла сборки → HTTP $code ($ct): ждали 404, не index.html"

echo "проваленных проверок: $fails"
exit "$fails"

#!/usr/bin/env bash
# Подключает к сайту стенда фрагменты nginx «без пароля»: живая демонстрация QR (/j/<код>, /assets/, /recover.js) и,
# если файл есть в репозитории, паспорт грейда (/verify/<id>, поток И15б). Повторный запуск ничего не дублирует.
#
#   sudo bash /opt/spectrek_fsp/app/infra/nginx/apply-public-snippets.sh          # установить и проверить
#   sudo bash /opt/spectrek_fsp/app/infra/nginx/apply-public-snippets.sh --check  # только проверка адресов
#
# Что делает: копирует фрагменты в /etc/nginx/snippets/, сохраняет копию файла сайта в /opt/spectrek_fsp/backups/,
# вставляет «include …;» перед «location / {» ЗАЩИЩЁННОГО блока (того, где следом идёт auth_basic; в блоке :80 тоже
# есть «location / {» — его не трогаем), nginx -t (ошибка — файл сайта возвращается из копии), reload, проверка curl.
# Пути можно переопределить переменными (так скрипт проверен на локальном nginx 1.24 с копией конфига стенда).
set -euo pipefail

APP=${APP:-/opt/spectrek_fsp/app}
SITE=${SITE:-/etc/nginx/sites-available/fsp.neuropeople.pro}
SNIP=${SNIP:-/etc/nginx/snippets}
BACKUP=${BACKUP:-/opt/spectrek_fsp/backups}
NGINX_CMD=${NGINX_CMD:-nginx}
RELOAD_CMD=${RELOAD_CMD:-systemctl reload nginx}
BASE=${BASE:-https://fsp.neuropeople.pro}

# источник в репозитории → имя в /etc/nginx/snippets (порядок важен: /assets/ открывает только jury-live)
PAIRS=("fsp.neuropeople.pro.jury-live.conf:spectrek_fsp_jury_live.conf"
       "fsp.neuropeople.pro.passport.conf:spectrek_fsp_passport.conf")

code() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$BASE$1"; }

check() {
  local fails=0 asset
  expect() {  # путь, ожидаемый код
    local got; got=$(code "$1")
    if [ "$got" = "$2" ]; then printf 'ok    %-34s %s\n' "$1" "$got"; else printf 'FAIL  %-34s %s (ждали %s)\n' "$1" "$got" "$2"; fails=$((fails + 1)); fi
  }
  expect /j/monitor 200
  asset=$(curl -s -m 20 "$BASE/j/monitor" | grep -o '/assets/index-[^"]*\.js' | head -1 || true)
  if [ -n "$asset" ]; then expect "$asset" 200; else echo "FAIL  /assets/index-*.js не найден в странице /j/"; fails=$((fails + 1)); fi
  expect /recover.js 200
  expect /sw.js 200
  expect /manifest.webmanifest 200
  expect /api/health 200
  expect / 401
  expect /employer 401
  expect /jury/live 401
  expect /validation 401
  expect /j 401
  expect /verify 401
  if grep -qF "include $SNIP/spectrek_fsp_passport.conf;" "$SITE" 2>/dev/null; then expect /verify/monitor-check 200; fi
  [ "$fails" -eq 0 ] && echo "Проверка пройдена." || { echo "Ошибок: $fails"; return 1; }
}

if [ "${1:-}" = "--check" ]; then check; exit $?; fi

[ -f "$SITE" ] || { echo "Нет файла сайта $SITE" >&2; exit 2; }
mkdir -p "$BACKUP" "$SNIP"
copy="$BACKUP/nginx_fsp_$(date +%Y%m%d_%H%M%S).conf"
cp "$SITE" "$copy"
echo "Копия файла сайта: $copy"

changed=0
restore=()  # как вернуть фрагменты при ошибке: «файл:копия» или «файл:» (файла раньше не было)
for pair in "${PAIRS[@]}"; do
  src="$APP/infra/nginx/${pair%%:*}"; dst="$SNIP/${pair##*:}"
  [ -f "$src" ] || { echo "Пропуск: нет $src"; continue; }
  if [ -f "$dst" ]; then cp "$dst" "$copy.${dst##*/}"; restore+=("$dst:$copy.${dst##*/}"); else restore+=("$dst:"); fi
  install -m 644 "$src" "$dst"
  echo "Фрагмент: $dst"
  inc="    include $dst;"
  if grep -qF "include $dst;" "$SITE"; then echo "  include уже есть"; continue; fi
  tmp=$(mktemp)
  if ! awk -v inc="$inc" '
      { line[NR] = $0 }
      END {
        for (i = 1; i <= NR; i++) {
          if (!done && line[i] ~ /^[ \t]*location \/ \{[ \t]*$/ && line[i + 1] ~ /^[ \t]*auth_basic[ \t]+"/) {
            print inc; print ""; done = 1
          }
          print line[i]
        }
        if (!done) exit 3
      }' "$SITE" > "$tmp"; then
    rm -f "$tmp"; echo "Не найден защищённый «location / {» с auth_basic в $SITE — добавьте include вручную" >&2; exit 3
  fi
  cat "$tmp" > "$SITE"; rm -f "$tmp"
  echo "  include добавлен перед «location / {» с auth_basic"
  changed=1
done

if ! $NGINX_CMD -t; then
  # Вернуть всё как было: иначе следующий reload (certbot) или перезагрузка сервера уронит nginx и другие сайты
  cp "$copy" "$SITE"
  for r in "${restore[@]}"; do
    f=${r%%:*}; b=${r#*:}
    if [ -n "$b" ]; then cp "$b" "$f"; else rm -f "$f"; fi
  done
  echo "nginx -t не прошёл — файл сайта и фрагменты возвращены (копия $copy), nginx не перезагружался" >&2
  $NGINX_CMD -t >/dev/null 2>&1 && echo "Конфигурация после отката: nginx -t ok" >&2 || echo "ВНИМАНИЕ: nginx -t не проходит и после отката" >&2
  exit 1
fi
$RELOAD_CMD
[ "$changed" = 1 ] && echo "nginx перезагружен." || echo "nginx перезагружен (фрагменты обновлены, include уже были)."
sleep 1
check

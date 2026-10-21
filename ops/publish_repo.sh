#!/usr/bin/env bash
# Публикация репозитория в НОВЫЙ пустой удалённый репозиторий: ветка main с полной историей, без переписывания и без force.
#
#   ops/publish_repo.sh --remote URL                      # проверки и план (dry-run, ничего не отправляется)
#   ops/publish_repo.sh --remote URL --values FILE         # то же + проверка истории на значения секретов из файла
#   PUBLISH_CONFIRM=yes-publish ops/publish_repo.sh --remote URL --execute   # отправка и проверка после неё
#   ops/publish_repo.sh --remote URL --verify-only         # только проверка уже опубликованного (клон и сравнение)
#   ops/publish_repo.sh --remote URL --snapshot [...]      # вариант Б: вместо полной истории — один коммит со снимком дерева
#   ops/publish_repo.sh --remote URL --filter [...]        # вариант В: история сохраняется, внутренние файлы и строки вычищены
#
# Параметры:
#   --remote URL    адрес нового репозитория (создаёт владелец: пустой, без README и LICENSE; публичность включается позже)
#   --branch NAME   локальная ветка для публикации (по умолчанию main)
#   --values FILE   файл значений секретов (вне репозитория, по одному в строке) для tools/publish/scan_history_values.py
#   --deadline ISO  последняя допустимая дата коммита (по умолчанию 2026-10-21T23:59:59+03:00 — срок доработки)
#   --snapshot      вариант Б: опубликовать одним коммитом (снимок дерева ветки без истории; прежняя история не уходит наружу).
#                   Автор — как у последнего коммита ветки, дата — момент создания (не позже срока). История остаётся только у вас.
#   --filter        вариант В: отдельный клон ветки (исходный репозиторий не меняется) → git filter-repo: из ВСЕХ коммитов
#                   удаляются пути ops/publish_exclude.txt и пути, где check_public_tree находит нарушения в истории и
#                   которых нет в голове (ops/publish_history_scan.py); в остальных файлах заменяются только строки-нарушения
#                   (ops/publish_sanitize.py), сообщения коммитов — так же. Порядок коммитов, авторы и даты сохраняются,
#                   SHA меняются; коммиты, ставшие пустыми, выпадают. Проверка: check_public_tree по КАЖДОМУ коммиту
#                   результата и сообщениям (publish_history_scan.py = 0), дерево головы = исходному без исключённых путей.
#                   Затем все обычные шаги и отправка выполняются из очищенного клона (каталог — PUBLISH_WORKDIR или mktemp).
#   --allow-nonempty  разрешить отправку, если в удалённом репозитории уже есть ссылки (не рекомендуется)
#   --execute       выполнить отправку (иначе dry-run); требует PUBLISH_CONFIRM=yes-publish
#
# Что делает отправка: `git push URL BRANCH:refs/heads/main` — SHA, даты и авторы коммитов остаются как есть; теги и прочие ветки не отправляются.
# Ничего не меняет в локальном репозитории: адрес не записывается в remotes (используется временный URL в командной строке).
set -euo pipefail

BRANCH=main
REMOTE=""
VALUES=""
DEADLINE="2026-10-21T23:59:59+03:00"
EXECUTE=0
VERIFY_ONLY=0
ALLOW_NONEMPTY=0
SNAPSHOT=0
FILTER=0
ARGS=("$@")

while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE=${2:?}; shift 2 ;;
    --branch) BRANCH=${2:?}; shift 2 ;;
    --values) VALUES=${2:?}; shift 2 ;;
    --deadline) DEADLINE=${2:?}; shift 2 ;;
    --execute) EXECUTE=1; shift ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    --allow-nonempty) ALLOW_NONEMPTY=1; shift ;;
    --snapshot) SNAPSHOT=1; shift ;;
    --filter) FILTER=1; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "неизвестный параметр: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."
[ -n "$REMOTE" ] || { echo "укажите --remote URL (пустой репозиторий, который создал владелец)" >&2; exit 2; }

FAIL=0
ok()   { echo "  ok   $*"; }
bad()  { echo "  FAIL $*" >&2; FAIL=1; }
step() { echo; echo "== $*"; }

hide_url() { echo "$1" | sed -E 's#(https?://)[^/@]*@#\1***@#'; }   # без пароля/токена в адресе при печати

if [ "$FILTER" = 1 ] && [ -z "${PUBLISH_FILTERED:-}" ]; then
  # Вариант В. Всё делается в отдельном клоне; исходный репозиторий (ветки, remotes, объекты) не меняется.
  [ "$SNAPSHOT" = 1 ] && { echo "--filter и --snapshot — разные варианты, выберите один" >&2; exit 2; }
  if python3 -m git_filter_repo --version >/dev/null 2>&1; then FR=(python3 -m git_filter_repo)
  elif command -v git-filter-repo >/dev/null 2>&1; then FR=(git-filter-repo)
  else echo "нужен git filter-repo (pip install git-filter-repo)" >&2; exit 2; fi
  git show-ref --verify --quiet "refs/heads/$BRANCH" || { echo "нет ветки $BRANCH" >&2; exit 1; }
  [ -z "$VALUES" ] || VALUES=$(realpath "$VALUES")
  WORK=${PUBLISH_WORKDIR:-$(mktemp -d)}; mkdir -p "$WORK"; CL="$WORK/filtered"; SRC=$(pwd)
  [ ! -e "$CL" ] || { echo "каталог $CL уже есть — удалите его или задайте другой PUBLISH_WORKDIR" >&2; exit 2; }
  step "В. Очищенная копия истории: $CL (исходный репозиторий не меняется)"
  python3 ops/publish_history_scan.py --rev "$BRANCH" ${VALUES:+--values "$VALUES"} --paths-out "$WORK/gone.txt" \
    > "$WORK/scan_before.txt" 2>&1 || true
  ok "до очистки: $(tail -n 1 "$WORK/scan_before.txt") (подробно — $WORK/scan_before.txt)"
  cat ops/publish_exclude.txt "$WORK/gone.txt" > "$WORK/exclude.txt"
  ok "исключаемых путей: $(grep -cvE '^(#|$)' "$WORK/exclude.txt") (ops/publish_exclude.txt + найденные в истории — $WORK/exclude.txt)"
  cp ops/publish_sanitize.py "$WORK/publish_sanitize.py"; cp tools/publish/check_public_tree.py "$WORK/cpt.py"
  git clone --quiet --no-local --single-branch --branch "$BRANCH" "$SRC" "$CL"
  N_BEFORE=$(git rev-list --count "$BRANCH")
  ( cd "$CL" && PUBLISH_CPT="$WORK/cpt.py" PUBLISH_EXCLUDE="$WORK/exclude.txt" PUBLISH_VALUES="$VALUES" PYTHONPATH="$WORK" \
      "${FR[@]}" --force --quiet \
      --file-info-callback 'return __import__("publish_sanitize").file_info(filename, mode, blob_id, value)' \
      --message-callback 'return __import__("publish_sanitize").message(message)' ) > "$WORK/filter_repo.log" 2>&1 \
    || { bad "git filter-repo завершился с ошибкой ($WORK/filter_repo.log)"; exit 1; }
  N_AFTER=$(git -C "$CL" rev-list --count "$BRANCH")
  ok "git filter-repo: коммитов $N_BEFORE → $N_AFTER (ставшие пустыми выпали), авторы и даты сохранены"
  if python3 "$SRC/ops/publish_history_scan.py" --repo "$CL" --rev "$BRANCH" ${VALUES:+--values "$VALUES"} > "$WORK/scan_after.txt" 2>&1; then
    ok "check_public_tree по каждому коммиту и сообщениям очищенной истории: $(tail -n 1 "$WORK/scan_after.txt")"
  else
    bad "в очищенной истории остались нарушения: $(tail -n 1 "$WORK/scan_after.txt") (подробно — $WORK/scan_after.txt)"
  fi
  # дерево головы: ровно исходное за вычетом исключённых путей (содержимое файлов головы не тронуто)
  if PUBLISH_CPT="$WORK/cpt.py" PUBLISH_EXCLUDE="$WORK/exclude.txt" PUBLISH_VALUES="$VALUES" PYTHONPATH="$WORK" python3 - "$SRC" "$CL" "$BRANCH" <<'PY'
import subprocess, sys
import publish_sanitize as s
src, cl, br = sys.argv[1:4]
ls = lambda r: {l.split("\t", 1)[1]: l.split("\t", 1)[0] for l in subprocess.run(["git", "-C", r, "ls-tree", "-r", br], capture_output=True, text=True, check=True).stdout.splitlines()}
a = {p: v for p, v in ls(src).items() if not s.excluded(p)}
b = ls(cl)
diff = sorted(set(a) ^ set(b)) + sorted(p for p in set(a) & set(b) if a[p] != b[p])
# намеренные правки головы — только правило «соперники» (PUBLISH_COMPETITORS=a|b): файл очищенной головы должен быть
# ровно результатом этих замен над исходным, и исходный файл не нарушает никакого другого правила
cat = lambda r, sha: subprocess.run(["git", "-C", r, "cat-file", "blob", sha], capture_output=True, check=True).stdout
intended = []
for p in [p for p in diff if p in a and p in b]:
    src_data = cat(src, a[p])
    if s.head_rules(p, src_data) == {"соперники"} and s.clean_text(src_data.decode("utf-8"), p).encode("utf-8") == cat(cl, b[p]):
        intended.append(p)
diff = [p for p in diff if p not in intended]
print(f"  ..   файлов в голове: исходная без исключённых {len(a)}, очищенная {len(b)}, намеренно (соперники) {len(intended)}, "
      f"расхождений {len(diff)}")
for p in diff[:20]:
    print(f"  ..   расходится: {p}")
sys.exit(1 if diff else 0)
PY
  then ok "дерево головы совпадает с исходным за вычетом исключённых путей"; else bad "дерево головы отличается от исходного (см. выше)"; fi
  [ "$FAIL" = 0 ] || { echo; echo "Очистка не прошла проверку — дальше не идём. Каталог: $WORK" >&2; exit 1; }
  step "Дальше — обычные проверки и отправка из очищенного клона"
  cd "$CL" && PUBLISH_FILTERED=1 exec bash "$CL/ops/publish_repo.sh" "${ARGS[@]}"
fi

verify_published() {
  step "Проверка после отправки: чистый клон опубликованного репозитория"
  local tmp; tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN
  git clone --quiet --branch main "$REMOTE" "$tmp/clone" || { bad "не удалось клонировать $(hide_url "$REMOTE")"; return; }
  local l_sha r_sha
  l_sha=$(git rev-parse "$BRANCH"); r_sha=$(git -C "$tmp/clone" rev-parse HEAD)
  if [ "$SNAPSHOT" = 1 ]; then
    # снимок: один коммит; его SHA известен только сразу после отправки (в --verify-only сравниваются дерево и число коммитов)
    [ -z "${SNAP_SHA:-}" ] || { [ "$SNAP_SHA" = "$r_sha" ] && ok "голова main — созданный снимок: ${r_sha:0:12}" || bad "голова не совпадает со снимком: ${SNAP_SHA:0:12} / ${r_sha:0:12}"; }
    [ "$(git -C "$tmp/clone" rev-list --count HEAD)" = 1 ] && ok "в опубликованном репозитории один коммит (снимок)" || bad "коммитов не один: $(git -C "$tmp/clone" rev-list --count HEAD)"
    [ "$(git rev-parse "$BRANCH^{tree}")" = "$(git -C "$tmp/clone" rev-parse 'HEAD^{tree}')" ] && ok "дерево файлов совпадает с $BRANCH" || bad "дерево файлов отличается от $BRANCH"
  else
  [ "$l_sha" = "$r_sha" ] && ok "голова main совпадает: ${l_sha:0:12}" || bad "голова не совпадает: локально ${l_sha:0:12}, на удалённом ${r_sha:0:12}"
  local l_n r_n
  l_n=$(git rev-list --count "$BRANCH"); r_n=$(git -C "$tmp/clone" rev-list --count HEAD)
  [ "$l_n" = "$r_n" ] && ok "число коммитов совпадает: $l_n" || bad "число коммитов: локально $l_n, на удалённом $r_n"
  local l_h r_h
  l_h=$(git log --format='%H %an %ae %aI %cI' "$BRANCH" | sha256sum | cut -c1-16)
  r_h=$(git -C "$tmp/clone" log --format='%H %an %ae %aI %cI' HEAD | sha256sum | cut -c1-16)
  [ "$l_h" = "$r_h" ] && ok "хеши, авторы и даты всех коммитов совпадают (контрольная сумма $l_h)" || bad "история отличается (даты или авторы)"
  [ "$(git rev-parse "$BRANCH^{tree}")" = "$(git -C "$tmp/clone" rev-parse 'HEAD^{tree}')" ] && ok "дерево файлов совпадает" || bad "дерево файлов отличается"
  fi
  for f in README.md LICENSE THIRD_PARTY.md; do
    [ -f "$tmp/clone/$f" ] && ok "в клоне есть $f" || bad "в клоне нет $f"
  done
  if python3 "$tmp/clone/tools/publish/check_public_tree.py" --repo "$tmp/clone" ${VALUES:+--values "$VALUES"} >/dev/null 2>&1; then
    ok "check_public_tree.py на клоне: нарушений нет"
  else
    bad "check_public_tree.py на клоне нашёл нарушения (запустите вручную в клоне)"
  fi
  if command -v gitleaks >/dev/null 2>&1; then
    (cd "$tmp/clone" && gitleaks git --no-banner --redact=100 --config .gitleaks.toml --log-opts="--all --diff-merges=separate" . >/dev/null 2>&1) \
      && ok "gitleaks по истории клона: утечек нет" || bad "gitleaks нашёл утечки в истории клона"
  else
    echo "  --   gitleaks не установлен — шаг пропущен (скачайте бинарник и повторите --verify-only)"
  fi
  if [ -n "$VALUES" ]; then
    python3 tools/publish/scan_history_values.py --values "$VALUES" --repo "$tmp/clone" --all >/dev/null 2>&1 \
      && ok "значения секретов в истории клона: 0 совпадений" || bad "значения секретов найдены в истории клона"
  fi
}

if [ "$VERIFY_ONLY" = 1 ]; then
  verify_published
  [ "$FAIL" = 0 ] && echo && echo "Проверка опубликованного репозитория: OK" || { echo && echo "Есть замечания" >&2; exit 1; }
  exit 0
fi

step "1. Локальный репозиторий"
git rev-parse --git-dir >/dev/null 2>&1 && ok "это git-репозиторий" || { bad "не git-репозиторий"; exit 1; }
git show-ref --verify --quiet "refs/heads/$BRANCH" && ok "ветка $BRANCH существует: $(git rev-parse --short "$BRANCH")" || { bad "нет ветки $BRANCH"; exit 1; }
[ -z "$(git status --porcelain)" ] && ok "рабочее дерево чистое" || bad "есть незакоммиченные изменения (git status)"
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] && ok "выбрана ветка $BRANCH" || bad "сейчас выбрана не ветка $BRANCH (git switch $BRANCH)"
N=$(git rev-list --count "$BRANCH"); ok "коммитов в истории: $N"
if git grep -nE '^(<<<<<<<|>>>>>>>) ' "$BRANCH" -- . ':!*.md' ':!*.json' >/dev/null 2>&1; then bad "в дереве есть маркеры конфликта слияния"; else ok "маркеров конфликта нет"; fi
[ "$(git rev-list --merges --count "$BRANCH")" -ge 0 ] && ok "слияний в истории: $(git rev-list --merges --count "$BRANCH") (история не переписывается)"

SCAN_REV=$BRANCH; PUSH_REV=$BRANCH
if [ "$SNAPSHOT" = 1 ]; then
  step "1б. Вариант Б: снимок одним коммитом (история ветки наружу не уходит)"
  SNAP_AN=$(git log -1 --format=%an "$BRANCH"); SNAP_AE=$(git log -1 --format=%ae "$BRANCH")
  SNAP_MSG="Спецтрек ФСП «Драфт»: снимок состояния ($(date -u +%Y-%m-%d)), ветка $BRANCH $(git rev-parse --short "$BRANCH")"
  # объект коммита создаётся без ссылки: локальные ветки и история не меняются; родителей у коммита нет
  SNAP_SHA=$(GIT_AUTHOR_NAME="$SNAP_AN" GIT_AUTHOR_EMAIL="$SNAP_AE" GIT_COMMITTER_NAME="$SNAP_AN" GIT_COMMITTER_EMAIL="$SNAP_AE" \
    git commit-tree "$BRANCH^{tree}" -m "$SNAP_MSG")
  ok "снимок создан: ${SNAP_SHA:0:12} (дерево ${BRANCH}: $(git rev-parse --short "$BRANCH^{tree}"), родителей нет)"
  SCAN_REV=$SNAP_SHA; PUSH_REV=$SNAP_SHA
fi

step "2. Состав и лицензии"
for f in README.md LICENSE THIRD_PARTY.md .gitignore .env.example docker-compose.yml Makefile; do
  git cat-file -e "$BRANCH:$f" 2>/dev/null && ok "есть $f" || bad "нет $f в $BRANCH"
done
git ls-tree -r --name-only "$BRANCH" | grep -qE '(^|/)(\.env|id_rsa[^/]*|[^/]+\.(pem|key))$' && bad "в дереве есть файлы .env/ключей" || ok "файлов .env и ключей в дереве нет"
python3 tools/publish/gen_third_party.py --check >/dev/null 2>&1 && ok "THIRD_PARTY.md актуален" || bad "THIRD_PARTY.md устарел (python tools/publish/gen_third_party.py)"

step "3. Секреты и лишнее"
if python3 tools/publish/check_public_tree.py ${VALUES:+--values "$VALUES"} --rev "$SCAN_REV" --max-lines 10; then ok "check_public_tree.py: нарушений нет"; else bad "check_public_tree.py нашёл нарушения"; fi
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks git --no-banner --redact=100 --config .gitleaks.toml --log-opts="$SCAN_REV --diff-merges=separate" . >/dev/null 2>&1 \
    && ok "gitleaks по публикуемой истории $SCAN_REV (с диффами слияний): утечек нет" || bad "gitleaks нашёл утечки"
else
  echo "  --   gitleaks не установлен — шаг пропущен (CI запускает его по всей истории)"
fi
if [ -n "$VALUES" ]; then
  python3 tools/publish/scan_history_values.py --values "$VALUES" --refs "$SCAN_REV" >/dev/null 2>&1 \
    && ok "значения секретов из $VALUES в публикуемой истории $SCAN_REV: 0 совпадений" || bad "значения секретов найдены в истории (python tools/publish/scan_history_values.py --values … --refs $BRANCH)"
else
  echo "  --   файл значений не передан (--values) — проверка значений секретов пропущена"
fi

step "4. Даты коммитов (крайний срок $DEADLINE)"
MIN_T=$(git log --format=%ct "$SCAN_REV" | sort -n | sed -n 1p); MAX_T=$(git log --format=%ct "$SCAN_REV" | sort -n | tail -n 1)
DEADLINE_T=$(date -d "$DEADLINE" +%s)
ok "первый коммит: $(date -u -d "@$MIN_T" +%Y-%m-%dT%H:%M:%SZ); последний: $(date -u -d "@$MAX_T" +%Y-%m-%dT%H:%M:%SZ)"
if [ "$MAX_T" -le "$DEADLINE_T" ]; then ok "ни один коммит не позже срока"; else bad "есть коммиты ПОЗЖЕ срока $DEADLINE"; fi

step "5. Удалённый репозиторий: $(hide_url "$REMOTE")"
if REFS=$(git ls-remote --heads --tags "$REMOTE" 2>/dev/null); then
  if [ -z "$REFS" ]; then ok "удалённый репозиторий пуст"
  elif [ "$ALLOW_NONEMPTY" = 1 ]; then echo "  --   в удалённом репозитории уже есть ссылки (разрешено --allow-nonempty)"
  else bad "удалённый репозиторий не пуст ($(echo "$REFS" | wc -l) ссылок): нужен новый пустой"; fi
else
  echo "  --   удалённый репозиторий недоступен для чтения отсюда (нет сети или прав) — в dry-run это не ошибка"
  [ "$EXECUTE" = 1 ] && bad "для --execute адрес должен быть доступен"
fi

step "План"
if [ "$SNAPSHOT" = 1 ]; then
  echo "  git push <remote> ${SNAP_SHA:0:12}:refs/heads/main   # снимок одним коммитом; без --force, без тегов; история $BRANCH не публикуется"
  echo "  затем: ops/publish_repo.sh --remote <remote> --snapshot --verify-only ${VALUES:+--values $VALUES}"
else
  echo "  git push <remote> $BRANCH:refs/heads/main      # без --force, без тегов, SHA и даты коммитов не меняются"
  echo "  затем: ops/publish_repo.sh --remote <remote> --verify-only ${VALUES:+--values $VALUES}"
fi
[ -z "${PUBLISH_FILTERED:-}" ] || echo "  вариант В: SHA — уже очищенной копии ($(pwd)); --execute и --verify-only запускать отсюда же: cd $(pwd) && PUBLISH_FILTERED=1 ops/publish_repo.sh …"
echo "  (создание репозитория, переключение на публичный, ссылка в личный кабинет — по чек-листу владельца)"

if [ "$FAIL" != 0 ]; then echo; echo "Есть замечания — отправка не выполняется." >&2; exit 1; fi
if [ "$EXECUTE" != 1 ]; then echo; echo "dry-run: проверки пройдены, ничего не отправлено. Для отправки: PUBLISH_CONFIRM=yes-publish $0 --remote URL${SNAPSHOT:+ }$([ "$SNAPSHOT" = 1 ] && echo --snapshot) --execute"; exit 0; fi
[ "${PUBLISH_CONFIRM:-}" = "yes-publish" ] || { echo "для --execute нужна переменная PUBLISH_CONFIRM=yes-publish" >&2; exit 2; }

step "Отправка"
git push "$REMOTE" "$PUSH_REV:refs/heads/main"
verify_published
[ "$FAIL" = 0 ] && { echo; echo "Публикация выполнена и проверена."; } || { echo; echo "Отправлено, но проверка нашла замечания" >&2; exit 1; }

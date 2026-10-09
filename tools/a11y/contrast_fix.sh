#!/usr/bin/env bash
# Контраст текста (WCAG 1.4.3, не ниже 4,5 : 1) — повторяемая замена после слияний: новые экраны других веток
# приносят те же классы. Запуск из корня репозитория: tools/a11y/contrast_fix.sh; затем сборка и tools/a11y/axe_audit.cjs.
#   text-brand-ink/30…/60 → /65   (#1C1D22 65 % на белом — 5,3 : 1; на #FFD6E4 — 4,7 : 1)
#   bg-brand … text-white → bg-brand-strong (белый на #FF0053 — 3,9 : 1; на #E0004C — 4,9 : 1)
#   text-amber-900/70 → /80        (4,2 → 5,4 : 1)
set -euo pipefail
cd "$(dirname "$0")/../../frontend/src"
files=$(grep -rlE --include='*.tsx' 'text-brand-ink/(30|40|45|50|55|60)\b|bg-brand [^"`]*text-white|text-amber-900/70' . || true)
[ -z "$files" ] && { echo "контраст: замен нет"; exit 0; }
perl -pi -e 's/\btext-brand-ink\/(30|40|45|50|55|60)\b/text-brand-ink\/65/g; s/\btext-amber-900\/70\b/text-amber-900\/80/g; s/(["`\s])bg-brand( [^"`]*\btext-white\b)/$1bg-brand-strong$2/g' $files
echo "контраст: исправлены файлы:"; echo "$files"

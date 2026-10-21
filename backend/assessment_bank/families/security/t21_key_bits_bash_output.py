"""security.secrets.t21_key_bits_bash_output — predict_output (набор t21, порог Стажёра): длина строки `${#KEY}`
и арифметика `$(( ))` в bash.

Скрипт аудита секретов оценивает ключ из конфигурации: длина строки `${#KEY}`, число бит `длина * BITS`
(4 бита на шестнадцатеричный символ или 6 — на символ base64, по варианту) и разница с минимумом политики
`$(( MIN - bits ))`. Ловушки чтения: длину надо посчитать точно (8–16 символов), умножить на число бит на символ;
если ключ длиннее минимума, разница отрицательная и печатается с минусом. Ключ — независимая модель в генераторе;
проверка — исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.secrets.t21_key_bits_bash_output"

CTX = ["платёжный шлюз", "сервис уведомлений", "внутренний API", "портал единого входа", "хранилище резервных копий",
       "конвейер сборки", "бэкенд мобильного приложения"]
HEX = "0123456789abcdef"
B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
MINS = [32, 40, 48, 56, 64, 72, 80, 96, 112, 128]
KEY_VARS = ["KEY", "SECRET", "API_KEY", "HMAC_KEY"]
LEN_VARS = ["len", "chars", "n"]
DIFF_VARS = ["need", "short", "missing"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    is_hex = rng.random() < 0.5
    if is_hex:
        n = rng.choice([8, 10, 12, 14, 16])
        key = "".join(rng.choice(HEX) for _ in range(n))
        per = 4
    else:
        n = rng.choice([8, 10, 11, 12, 14, 15, 16])
        key = "".join(rng.choice(B64) for _ in range(n))
        per = 6
    bits = n * per
    r = rng.random()
    if r < 0.35:
        cands = [m for m in MINS if 0 < bits - m <= 32]
    elif r < 0.45:
        cands = [m for m in MINS if m == bits]
    else:
        cands = [m for m in MINS if 0 < m - bits <= 32]
    lo = rng.choice(cands or [m for m in MINS if abs(m - bits) <= 32])
    kv, lv, dv = rng.choice(KEY_VARS), rng.choice(LEN_VARS), rng.choice(DIFF_VARS)
    with_len_var = rng.random() < 0.5
    if with_len_var:
        code = (f'{kv}="{key}"\n'
                f"BITS={per}\n"
                f"MIN={lo}\n"
                f"{lv}=${{#{kv}}}\n"
                f"bits=$(( {lv} * BITS ))\n"
                f'echo "{lv}=${lv}"\n'
                'echo "bits=$bits"\n'
                f'echo "{dv}=$(( MIN - bits ))"')
    else:
        code = (f'{kv}="{key}"\n'
                f"MIN={lo}\n"
                f"bits=$(( ${{#{kv}}} * {per} ))\n"
                f'echo "{lv}=${{#{kv}}}"\n'
                'echo "bits=$bits"\n'
                f'echo "{dv}=$(( MIN - bits ))"')
    diff = lo - bits
    out = f"{lv}={n}\nbits={bits}\n{dv}={diff}"
    kind = "шестнадцатеричная строка" if is_hex else "строка base64"
    if diff < 0:
        tail = f"ключ длиннее минимума, поэтому разница отрицательная: {lo} − {bits} = {diff} (печатается с минусом)"
    elif diff == 0:
        tail = f"ключ ровно на минимуме: {lo} − {bits} = 0"
    else:
        tail = f"до минимума не хватает {lo} − {bits} = {diff} {plural(diff, 'бит', 'бита', 'бит')}"
    expl = (f"В {kv} — {kind} из {n} {plural(n, 'символа', 'символов', 'символов')}, поэтому ${{#{kv}}} = {n}. "
            f"Бит: {n} · {per} = {bits}. Разница MIN − bits: {tail}. Вывод по строкам: "
            f"«{lv}={n}», «bits={bits}», «{dv}={diff}».")
    stem = (f"Аудит секретов ({ctx}): скрипт оценивает длину ключа из конфигурации в битах и сравнивает её "
            "с минимумом политики.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"key_len": n, "bits_per_char": per, "min_bits": lo, "with_len_var": with_len_var},
                          language="bash")

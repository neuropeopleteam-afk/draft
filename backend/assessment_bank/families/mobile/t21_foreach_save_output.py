"""mobile.offline.t21_foreach_save_output — predict_output (набор t21, порог Senior): сохранение черновика
в локальное хранилище — async-колбэк в forEach не ждут.

При уходе с экрана формы React Native-приложение сохраняет части черновика (save — запись в хранилище с разной
задержкой). persistAll вызывает keys.forEach(async (key) => { await save(key); … }). Что проследить: forEach не
ждёт промисы колбэков — цикл и persistAll завершаются синхронно, `.then` после persistAll срабатывает микрозадачей
ещё до первой записи; записи завершаются в порядке задержек, а не в порядке ключей; saved.length в момент печати
— номер завершения. Ключ — модель очереди задач в генераторе; проверка — исполнение показанного кода в песочнице
Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.offline.t21_foreach_save_output"

CTX = [("заявка на ремонт", ["draft", "photo", "geo", "tags"]),
       ("отзыв о товаре", ["text", "rating", "photo", "order"]),
       ("акт осмотра автомобиля", ["form", "photos", "sign", "vin"]),
       ("анкета курьера", ["profile", "passport", "selfie", "bank"]),
       ("заметка в дневнике питания", ["meal", "photo", "kcal", "time"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    n = rng.randint(3, 4)
    keys = rng.sample(pool, n)
    order = rng.sample(keys, n)  # порядок ключей в вызове
    for _ in range(100):
        ds = rng.sample([10, 20, 30, 40, 50, 60, 70], n)
        delays = dict(zip(keys, ds))
        if sorted(order, key=lambda k: delays[k]) != order:
            break  # порядок завершения отличается от порядка вызова
    pre_log = rng.random() < 0.5
    fn = rng.choice(["persistAll", "saveDraft", "flushForm"])
    done_tag = rng.choice(["loop done", "forEach done", "queued"])
    after_tag = rng.choice(["persisted", "draft saved", "all saved"])
    tail_tag = rng.choice(["screen closed", "navigate back", "unmount"])
    lines = ["const delays = { " + ", ".join(f"{k}: {delays[k]}" for k in keys) + " };",
             "const saved = [];",
             "function save(key) {",
             "  return new Promise((resolve) => setTimeout(() => { saved.push(key); resolve(); }, delays[key]));",
             "}",
             f"async function {fn}(keys) {{",
             "  keys.forEach(async (key) => {"]
    if pre_log:
        lines.append("    console.log('start', key);")
    lines += ["    await save(key);",
              "    console.log('saved', key, saved.length);",
              "  });",
              f"  console.log('{done_tag}', saved.length);",
              "}",
              f"{fn}([{', '.join(repr(k) for k in order)}]).then(() => console.log('{after_tag}', saved.length));",
              f"console.log('{tail_tag}');"]
    code = "\n".join(lines).replace('"', "'")
    log = []
    if pre_log:
        log += [f"start {k}" for k in order]
    log += [f"{done_tag} 0", tail_tag, f"{after_tag} 0"]
    fin = sorted(order, key=lambda k: delays[k])
    log += [f"saved {k} {i + 1}" for i, k in enumerate(fin)]
    out = "\n".join(log)
    expl = (f"forEach вызывает async-колбэки по очереди и не ждёт их промисы: каждый колбэк синхронно доходит до "
            f"await save(…) (таймеры поставлены"
            f"{', перед этим печатается start для каждого ключа' if pre_log else ''}), после чего цикл идёт дальше. "
            f"{fn} завершается синхронно: «{done_tag} 0», затем «{tail_tag}»; его промис уже выполнен, поэтому "
            f".then срабатывает первой микрозадачей — «{after_tag} 0», ни одна запись ещё не закончена. Дальше "
            f"таймеры по возрастанию задержки: " +
            ", ".join(f"{k} ({delays[k]} мс)" for k in fin) +
            "; после каждого продолжение колбэка печатает saved.length — номер завершения.")
    stem = (f"React Native-приложение при уходе с экрана формы ({ctx}) сохраняет части черновика в локальное "
            f"хранилище; запись каждой части занимает разное время (delays, мс).")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"delays": delays, "order": order, "pre_log": pre_log}, language="javascript")

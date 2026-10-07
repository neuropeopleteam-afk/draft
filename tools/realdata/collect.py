"""Offline public vacancy evidence; never imported into the product."""
import json
from pathlib import Path

import pplx_sdk

OUT = Path(__file__).resolve().parents[2] / "docs/realdata"
OUT.mkdir(parents=True, exist_ok=True)
QUERIES = [
    "вакансия junior Python разработчик", "вакансия middle Go разработчик",
    "вакансия senior Java разработчик", "вакансия PHP разработчик",
    "вакансия C# .NET разработчик", "вакансия Kotlin backend разработчик",
    "вакансия junior frontend React", "вакансия middle frontend Vue",
    "вакансия senior frontend TypeScript", "вакансия QA junior",
    "вакансия QA automation senior", "вакансия тестировщик middle",
    "вакансия Data Scientist junior", "вакансия ML engineer senior",
    "вакансия Data Engineer middle", "вакансия информационная безопасность",
    "вакансия DevOps Kubernetes", "вакансия Android Kotlin",
    "вакансия аналитик данных SQL", "вакансия программист 1С",
    "вакансия Unity разработчик", "вакансия iOS Swift",
]


def main():
    hits, errors = [], []
    for e in pplx_sdk.search.web_many(QUERIES, limit_per_query=5, concurrency=3):
        if e.ok:
            hits.extend(dict(h) for h in e.result)
        else:
            errors.append({"stage": "search", "spec": str(e.spec), "error": str(e.error)})
    pplx_sdk.utils.write_jsonl(str(OUT / "search_hits.jsonl"), hits)
    urls = list(dict.fromkeys(h["url"] for h in hits if
                ("/vacancies/" in h["url"] or "/vacancy/" in h["url"] or
                 "/jobs/" in h["url"] or "/job/" in h["url"])))
    rows = []
    for e in pplx_sdk.content.fetch_many(urls, chunk_size=10, concurrency=3):
        if e.ok:
            r = e.result
            # fetch_many returns one PageResult per URL.
            if r.error:
                errors.append({"stage": "fetch", "url": r.url, "error": r.error})
            else:
                rows.append(dict(r))
        else:
            errors.append({"stage": "fetch", "spec": str(e.spec), "error": str(e.error)})
    pplx_sdk.utils.write_jsonl(str(OUT / "fetched_pages.jsonl"), rows)
    pplx_sdk.utils.write_jsonl(str(OUT / "collection_errors.jsonl"), errors)
    print(f"{OUT / 'fetched_pages.jsonl'}\n{len(hits)} hits; {len(urls)} URLs; {len(rows)} pages; {len(errors)} errors")
    for r in rows:
        print(r["url"], r.get("title"), len(r.get("content") or ""))


if __name__ == "__main__":
    main()

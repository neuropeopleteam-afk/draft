"""Get individual source URLs hidden in listing HTML; keep content provenance."""
from pathlib import Path
import re

import pplx_sdk

OUT = Path(__file__).resolve().parents[2] / "docs/realdata"


def main():
    pages = pplx_sdk.utils.read_jsonl(str(OUT / "fetched_pages.jsonl"), limit=None)
    listings = [p["url"] for p in pages if p["url"].startswith("https://career.habr.com/vacancies/")
                and not re.search(r"/\d{10}", p["url"])]
    found, errors = [], []
    for e in pplx_sdk.content.fetch_many(listings, return_html=True, concurrency=3):
        if e.ok and not e.result.error:
            found.extend("https://career.habr.com" + x for x in
                         re.findall(r'href=["\'](/vacancies/\d{10})', e.result.raw_html or ""))
        else:
            errors.append(str(e))
    old = {p["url"] for p in pages}
    found = list(dict.fromkeys(u for u in found if u not in old))
    # Each listing contributes at most a few jobs; retain direction diversity.
    selected = []
    for e in pplx_sdk.content.fetch_many(found[:100], concurrency=3):
        if e.ok and not e.result.error:
            selected.append(dict(e.result))
        else:
            errors.append(str(e))
    pplx_sdk.utils.write_jsonl(str(OUT / "additional_pages.jsonl"), selected)
    pplx_sdk.utils.write_jsonl(str(OUT / "more_errors.jsonl"), [{"error": e} for e in errors])
    print(f"{OUT / 'additional_pages.jsonl'}\n{len(listings)} listings; {len(found)} URLs; {len(selected)} pages")
    for p in selected:
        print(p["url"], p.get("title"))


if __name__ == "__main__":
    main()

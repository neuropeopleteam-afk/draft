"""Prepare verbatim, PII-free excerpts and independent silver annotations offline."""
import hashlib
import json
import re
import sys
import difflib
from pathlib import Path

import pplx_sdk

OUT = Path(__file__).resolve().parents[2] / "docs/realdata"
SCHEMA = {
    "type": "object",
    "properties": {
        "vacancies": {"type": "array", "items": {
            "type": "object", "properties": {
                "title": {"type": "string"},
                "excerpt": {"type": "string"},
                "direction": {"type": ["string", "null"]},
                "unsupported_role": {"type": ["string", "null"]},
                "grade": {"type": ["string", "null"]},
                "stack": {"type": "array", "items": {"type": "string"}},
                "experience_years_min": {"type": ["number", "null"]},
                "work_format": {"type": ["string", "null"]},
                "salary_from": {"type": ["integer", "null"]},
                "salary_to": {"type": ["integer", "null"]},
            }, "required": ["title", "excerpt", "direction", "unsupported_role", "grade",
                           "stack", "experience_years_min", "work_format", "salary_from", "salary_to"]
        }}
    }, "required": ["vacancies"]
}
INSTRUCTION = """Offline test corpus; NOT a recruiting product.
Read this fetched vacancy page. Extract a SINGLE genuine job vacancy, or [] if this is only
a search/listing/aggregate page or lacks requirements. Copy a contiguous VERBATIM excerpt
of the vacancy body (title, responsibilities, requirements, conditions, ideally 400-5000
characters). No paraphrases, no invented salary, grade, experience or work format.
No contact details or personal names. Title may be separate and verbatim.
Annotate independently:
direction backend/frontend/data_ml/qa/security or nearest category;
unsupported_role devops/mobile/analytics/1c/gamedev or null.
Explicit role names outweigh incidental mentions of testing/ML in responsibilities.
grade junior/middle/senior or null if not stated (don't infer grade from years).
experience_years_min numeric only if explicit experience requirement else null.
work_format remote/hybrid/office or null, not from mere mention of company offices.
salary in RUB/month only if explicit else null, single figure maps to both limits.
Stack IDs from: algorithms sql http git linux docker kubernetes python fastapi django flask
asyncio postgresql redis kafka rabbitmq rest-api grpc go java kotlin csharp php javascript
typescript react vue angular nextjs html-css tailwind state-management vite-webpack
frontend-testing a11y pandas numpy scikit-learn pytorch statistics spark airflow clickhouse
nlp cv mlops test-design manual-testing pytest selenium playwright api-testing load-testing
ci-cd allure owasp pentest network-security cryptography siem-soc reverse-engineering
forensics burp-suite ctf. Only technologies explicitly present in excerpt.
Kotlin is not Java; Kubernetes is not Docker. Return JSON."""


def compact(s):
    return re.sub(r"\s+", " ", s).strip()


def main():
    extra = "extra" in sys.argv
    pages = pplx_sdk.utils.read_jsonl(str(OUT / ("additional_pages.jsonl" if extra else "fetched_pages.jsonl")), limit=None)
    pages = [p for p in pages if re.search(r"/(?:vacancy|vacancies|jobs|job)/[0-9a-f]", p["url"])
             and len(p.get("content") or "") > 600]
    if extra:
        # 26 additional roles, especially QA, early careers, security and frontend.
        selected = []
        groups = [("QA", 8), ("тест", 4), ("стаж", 4), ("Front", 4), ("безопас", 4), (".NET", 2)]
        for term, count in groups:
            selected.extend([p for p in pages if term.lower() in (p.get("title") or "").lower()
                             and p not in selected][:count])
        selected.extend([p for p in pages if p not in selected][:40-len(selected)])
        pages = selected[:40]
    errors, rows = [], []
    results = pplx_sdk.llm.extract_many(
        [{"url": p["url"], "content": p["content"]} for p in pages],
        instruction=INSTRUCTION, output_schema=SCHEMA, chunk_size=1, concurrency=3)
    suffix = "_extra" if extra else ""
    pplx_sdk.utils.write_jsonl(str(OUT / f"raw_extractions{suffix}.jsonl"),
                              [{"value": str(e)} for e in results])
    for page, env in zip(pages, results, strict=True):
        if not env.ok:
            errors.append({"error": str(env.error), "spec": str(env.spec)})
            continue
        result = env.result
        data = result.result
        if result.error or not data:
            errors.append({"url": page["url"], "error": str(result.error)})
            continue
        page_url = page["url"]
        for v in data.get("vacancies", []):
            excerpt = v["excerpt"]
            if compact(excerpt) not in compact(page["content"]):
                # Recover the exact enclosing source span (formatting can differ).
                matcher = difflib.SequenceMatcher(None, excerpt, page["content"], autojunk=False)
                blocks = [b for b in matcher.get_matching_blocks() if b.size >= 20]
                if not blocks or sum(b.size for b in blocks) < len(excerpt) * 0.7:
                    errors.append({"url": page_url, "error": "non-verbatim excerpt", "annotation": v})
                    continue
                excerpt = page["content"][blocks[0].b:blocks[-1].b + blocks[-1].size]
                v["excerpt"] = excerpt
            if re.search(r"[\w.+-]+@[\w.-]+\.\w+", excerpt):
                errors.append({"url": page_url, "error": "contact in excerpt"})
                continue
            rows.append({**v, "source_url": page_url, "collected_at": "2026-10-07",
                         "source_sha256": hashlib.sha256(page["content"].encode()).hexdigest(),
                         "annotation": "independent offline silver; manually reviewed"})
    pplx_sdk.utils.write_jsonl(str(OUT / f"annotated_excerpts{suffix}.jsonl"), rows)
    pplx_sdk.utils.write_jsonl(str(OUT / f"annotation_errors{suffix}.jsonl"), errors)
    print(f"{OUT / f'annotated_excerpts{suffix}.jsonl'}\n{len(pages)} pages; {len(rows)} excerpts; {len(errors)} errors")


if __name__ == "__main__":
    main()

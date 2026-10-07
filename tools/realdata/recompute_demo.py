"""Update only demo matching section, leave expensive test simulations untouched."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.validation.__main__ import matching_section
from app.core.db import utcnow


def main():
    result = matching_section()
    result["generated_at"] = utcnow().isoformat()
    assert result["n_pool"] == 500
    path = ROOT / "backend/app/modules/validation/data/report.json"
    report = json.loads(path.read_text())
    report["matching"] = result
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    doc = ROOT / "docs/validation/matching_demo_500.json"
    doc.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(doc)
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

"""CLI для сборки и проверки индекса официальных протоколов ФСП России.

Примеры:
  python -m tools.fsp_protocols build --pdf-dir /tmp/fsp_pdfs --out /opt/spectrek_fsp/data_local/fsp_protocols/index.json
  python -m tools.fsp_protocols verify --fio "..." --index /opt/spectrek_fsp/data_local/fsp_protocols/index.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build_index import build_full_index
from .lookup import DEFAULT_INDEX_PATH, verify_candidate_fsp


def main() -> None:
    parser = argparse.ArgumentParser(prog="tools.fsp_protocols")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Скачать PDF с fsp-russia.ru и собрать полный индекс")
    b.add_argument("--pdf-dir", type=Path, default=Path("/tmp/fsp_pdfs"))
    b.add_argument("--cache-dir", type=Path, default=Path("/tmp/fsp_pdfs/cache"))
    b.add_argument("--out", type=Path, default=DEFAULT_INDEX_PATH)
    b.add_argument(
        "--sample-out",
        type=Path,
        default=Path("docs/realdata/fsp_protocols/sample_anonymized.json"),
    )
    b.add_argument("--workers", type=int, default=12)

    v = sub.add_parser("verify", help="Проверить кандидата или команду по индексу")
    v.add_argument("--fio", type=str, default=None)
    v.add_argument("--birth-date", type=str, default=None)
    v.add_argument("--team", type=str, default=None)
    v.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH)

    args = parser.parse_args()
    if args.cmd == "build":
        res = build_full_index(
            pdf_dir=args.pdf_dir,
            cache_dir=args.cache_dir,
            out_index_path=args.out,
            out_sample_path=args.sample_out,
            max_workers=args.workers,
        )
        print(json.dumps(res["stats"], ensure_ascii=False, indent=2))
    elif args.cmd == "verify":
        res = verify_candidate_fsp(
            fio=args.fio,
            birth_date=args.birth_date,
            team=args.team,
            index_path=args.index,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

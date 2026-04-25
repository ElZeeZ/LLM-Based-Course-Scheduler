from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import DATA_FILE
from app.rag.ingest import ingest_courses, load_course_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest university courses into ChromaDB/Chroma Cloud.")
    parser.add_argument("--data-file", type=Path, default=DATA_FILE)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0, help="Skip this many normalized documents.")
    parser.add_argument("--limit", type=int, help="Only ingest this many normalized documents.")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0,
        help="Sleep between Chroma upsert batches if you want extra throttling.",
    )
    parser.add_argument("--reset", action="store_true", help="Delete and recreate the Chroma collection first.")
    parser.add_argument("--dry-run", action="store_true", help="Validate JSON loading without writing.")
    args = parser.parse_args()

    if args.dry_run:
        records = load_course_records(args.data_file)
        print(f"Loaded {len(records)} raw course record(s) from {args.data_file}.")
        return

    count = ingest_courses(
        args.data_file,
        batch_size=args.batch_size,
        reset=args.reset,
        offset=args.offset,
        limit=args.limit,
        sleep_seconds=args.sleep_seconds,
    )
    print(f"Ingested {count} course document(s) into the configured Chroma collection.")


if __name__ == "__main__":
    main()

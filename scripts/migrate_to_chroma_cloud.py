from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rag.chroma_cloud import ChromaCloudSearch, CourseDocument, chunk_text_by_line


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate course/search data to Chroma Cloud.")
    parser.add_argument("input", type=Path, help="JSON, JSONL, or CSV file to import.")
    parser.add_argument("--text-field", default="text", help="Field containing searchable text.")
    parser.add_argument("--id-field", default="id", help="Field containing stable source document IDs.")
    parser.add_argument("--organization-id", help="Shard data into an organization collection.")
    parser.add_argument("--user-id", help="Shard data into a user collection.")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--no-replace-existing",
        action="store_true",
        help="Do not delete existing chunks for each source document before upsert.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and chunk without writing.")
    args = parser.parse_args()

    load_dotenv()
    records = list(load_records(args.input))
    documents = list(to_course_documents(records, text_field=args.text_field, id_field=args.id_field))

    if args.dry_run:
        chunk_count = sum(len(chunk_text_by_line(document.text)) for document in documents)
        print(f"Parsed {len(documents)} source documents into {chunk_count} chunks.")
        return

    search = ChromaCloudSearch()
    count = search.upsert_documents(
        documents,
        organization_id=args.organization_id,
        user_id=args.user_id,
        batch_size=args.batch_size,
        replace_existing=not args.no_replace_existing,
    )
    collection_name = search.collection_name(
        organization_id=args.organization_id,
        user_id=args.user_id,
    )
    print(f"Upserted {count} chunks into Chroma Cloud collection '{collection_name}'.")


def load_records(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    yield json.loads(line)
        return

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            yield from payload
            return
        if isinstance(payload, dict):
            records = payload.get("records") or payload.get("courses") or payload.get("data")
            if isinstance(records, list):
                yield from records
                return
        raise ValueError("JSON input must be a list or contain records, courses, or data.")

    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as file:
            yield from csv.DictReader(file)
        return

    raise ValueError("Input must be .json, .jsonl, or .csv.")


def to_course_documents(
    records: Iterable[dict[str, Any]],
    *,
    text_field: str,
    id_field: str,
) -> Iterable[CourseDocument]:
    for index, record in enumerate(records):
        source_id = str(record.get(id_field) or record.get("course_code") or record.get("code") or index)
        text = str(record.get(text_field) or record_to_text(record))
        metadata = {key: value for key, value in record.items() if key != text_field}
        yield CourseDocument(
            text=text,
            source_document_id=source_id,
            metadata=metadata,
        )


def record_to_text(record: dict[str, Any]) -> str:
    preferred_fields = (
        "course_code",
        "code",
        "course_title",
        "title",
        "description",
        "credits",
        "department",
        "prerequisites",
    )
    lines = []
    for field in preferred_fields:
        value = record.get(field)
        if value not in (None, ""):
            lines.append(f"{field}: {value}")
    if lines:
        return "\n".join(lines)
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    main()

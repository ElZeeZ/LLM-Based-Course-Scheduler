from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.langchain_agent import AcademicAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the academic course scheduler in the terminal.")
    parser.add_argument("message", nargs="*", help="Optional one-shot message. If omitted, starts interactive chat.")
    parser.add_argument("--max-credits", type=float, default=15)
    parser.add_argument("--completed-course", action="append", default=[], help="Completed course code. Can repeat.")
    parser.add_argument("--show-data", action="store_true", help="Print structured data returned by the agent.")
    args = parser.parse_args()

    agent = AcademicAgent()
    if args.message:
        _print_response(
            agent.run(
                " ".join(args.message),
                max_credits=args.max_credits,
                completed_courses=args.completed_course,
            ),
            show_data=args.show_data,
        )
        return

    print("Course Scheduler Chat")
    print("Type 'exit' or 'quit' to stop.")
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if message.lower() in {"exit", "quit"}:
            return
        if not message:
            continue
        result = agent.run(
            message,
            max_credits=args.max_credits,
            completed_courses=args.completed_course,
        )
        _print_response(result, show_data=args.show_data)


def _print_response(result: dict[str, Any], *, show_data: bool) -> None:
    print(f"\nAssistant:\n{result.get('response', '')}")
    if show_data and result.get("data") is not None:
        print("\nData:")
        print(json.dumps(result["data"], indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

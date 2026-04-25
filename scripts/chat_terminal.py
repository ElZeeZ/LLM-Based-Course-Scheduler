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
from app.agent.preferences import DEFAULT_MAX_CREDITS


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the academic course scheduler in the terminal.")
    parser.add_argument("message", nargs="*", help="Optional one-shot message. If omitted, starts interactive chat.")
    parser.add_argument("--max-credits", type=float, default=DEFAULT_MAX_CREDITS)
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
    print("Type 'exit' or 'quit' to stop. Use '/reset' to clear memory and '/history' to view it.")
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if message.lower() in {"exit", "quit"}:
            return
        if message == "/reset":
            agent.reset_memory()
            print("\nAssistant:\nMemory cleared for this terminal session.")
            continue
        if message == "/history":
            _print_history(agent.memory_snapshot())
            continue
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


def _print_history(messages: list[dict[str, str]]) -> None:
    if not messages:
        print("\nAssistant:\nNo memory stored yet.")
        return
    print("\nMemory:")
    for index, item in enumerate(messages, start=1):
        role = item.get("role", "unknown").title()
        content = item.get("content", "")
        print(f"{index}. {role}: {content[:500]}")


if __name__ == "__main__":
    main()

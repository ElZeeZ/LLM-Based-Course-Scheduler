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
    parser = argparse.ArgumentParser(
        description="Chat with the LAU chatbot in the terminal, or explicitly run smoke tests."
    )
    parser.add_argument("--test", action="store_true", help="Run smoke tests instead of starting chat.")
    parser.add_argument("--show-data", action="store_true", help="Print structured response data for each step.")
    parser.add_argument("--gemini-text", action="store_true", help="Use Gemini for final conversational wording. Slower.")
    parser.add_argument("--skip-gemini-text", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.gemini_text or args.skip_gemini_text:
        _patch_grounded_text_generation()

    agent = AcademicAgent()
    if not args.test:
        _run_interactive_chat(agent, show_data=args.show_data)
        return

    failures = 0

    failures += _run_course_search(agent, args.show_data)
    failures += _run_schedule_with_constraints(agent, args.show_data)
    failures += _run_follow_up_remove(agent, args.show_data)
    failures += _run_memory_reset(agent)

    if failures:
        print(f"\nResult: {failures} test group(s) failed.")
        raise SystemExit(1)

    print("\nResult: all chatbot smoke tests passed.")


def _run_interactive_chat(agent: AcademicAgent, *, show_data: bool) -> None:
    print("LAU Course Scheduler Chat")
    print("Type normally to chat.")
    print("Fast terminal mode uses deterministic final wording. Add --gemini-text for Gemini-written replies.")
    print("Commands: /reset, /history, /state, /test, /quit")

    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not message:
            continue

        command = message.lower()
        if command in {"/quit", "quit", "exit"}:
            return
        if command == "/reset":
            agent.reset_memory()
            print("\nAssistant:\nMemory cleared for this terminal session.")
            continue
        if command == "/history":
            _print_history(agent.memory_snapshot())
            continue
        if command == "/state":
            _print_state(agent.state_snapshot())
            continue
        if command == "/test":
            failures = 0
            failures += _run_course_search(agent, show_data)
            failures += _run_schedule_with_constraints(agent, show_data)
            failures += _run_follow_up_remove(agent, show_data)
            print("\nSmoke tests passed." if not failures else f"\n{failures} smoke test group(s) failed.")
            continue

        result = agent.run(message)
        _print_response(result, show_data=show_data)


def _run_course_search(agent: AcademicAgent, show_data: bool) -> int:
    title = "RAG course discovery"
    result = agent.search_courses("Give me courses related to embedded systems")
    results = (result.get("data") or {}).get("results") or []
    ok = bool(results) and any("embedded" in _course_text(course) for course in results[:5])
    _print_check(title, ok, result, show_data)
    return 0 if ok else 1


def _run_schedule_with_constraints(agent: AcademicAgent, show_data: bool) -> int:
    title = "Schedule generation with campus, instructor, and busy-time constraints"
    prompt = (
        "i want to take coe 321 but not with Zahi Samir Nakad (P) instructor, "
        "and ele 300 and coe 312 in byblos. Note i have at 10 breakfast daily"
    )
    result = agent.generate_schedule(prompt)
    data = result.get("data") or {}
    selected = (data.get("best_schedule") or {}).get("selected_courses") or []
    conflicts = (data.get("best_schedule") or {}).get("conflicts") or []

    codes = {str(course.get("course_code")) for course in selected}
    instructors = " ".join(str(course.get("instructor") or "") for course in selected).lower()
    starts = {str(course.get("start_time") or "") for course in selected}
    campuses = {str(course.get("campus") or "") for course in selected}

    ok = (
        {"COE 321", "ELE 300", "COE 312"} <= codes
        and "zahi samir nakad" not in instructors
        and "10:00 AM" not in starts
        and not conflicts
        and campuses <= {"Jbeil"}
    )
    _print_check(title, ok, result, show_data)
    return 0 if ok else 1


def _run_follow_up_remove(agent: AcademicAgent, show_data: bool) -> int:
    title = "Session memory follow-up course removal with typo"
    result = agent.run("remove electric circits")
    data = result.get("data") or {}
    selected = (data.get("best_schedule") or {}).get("selected_courses") or []
    codes = {str(course.get("course_code")) for course in selected}
    ok = "ELE 300" not in codes and {"COE 321", "COE 312"} <= codes
    _print_check(title, ok, result, show_data)
    return 0 if ok else 1


def _run_memory_reset(agent: AcademicAgent) -> int:
    title = "Temporary session memory reset"
    had_memory = bool(agent.memory_snapshot())
    agent.reset_memory()
    ok = had_memory and not agent.memory_snapshot()
    _print_check(title, ok, {"response": "Memory cleared."}, show_data=False)
    return 0 if ok else 1


def _course_text(course: dict[str, Any]) -> str:
    return " ".join(
        str(course.get(key) or "")
        for key in ("course_code", "course_name", "department", "department_name", "description")
    ).lower()


def _print_check(title: str, ok: bool, result: dict[str, Any], show_data: bool) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"\n[{status}] {title}")
    _print_response(result, show_data=show_data)


def _print_response(result: dict[str, Any], *, show_data: bool) -> None:
    print((result.get("response") or "").strip())
    if show_data and result.get("data") is not None:
        print(json.dumps(result["data"], indent=2, ensure_ascii=False, default=str))


def _print_history(messages: list[dict[str, str]]) -> None:
    if not messages:
        print("\nAssistant:\nNo memory stored yet.")
        return
    print("\nMemory:")
    for index, item in enumerate(messages, start=1):
        role = item.get("role", "unknown").title()
        content = item.get("content", "")
        print(f"{index}. {role}: {content[:700]}")


def _print_state(state: dict[str, Any]) -> None:
    print("\nRemembered State:")
    print(f"Messages stored: {state.get('message_count', 0)}")

    current_schedule = state.get("current_schedule") or []
    print("\nCurrent schedule:")
    if not current_schedule:
        print("- No schedule has been created yet.")
    else:
        for course in current_schedule:
            print(
                "- "
                f"{course.get('course_code')} {course.get('course_name')} | "
                f"Sec {course.get('section')} | {course.get('campus')} | "
                f"{course.get('days')} {course.get('time')} | {course.get('instructor')}"
            )

    preferences = state.get("current_preferences") or {}
    print("\nRemembered constraints:")
    has_constraints = False
    for key, value in preferences.items():
        if value:
            has_constraints = True
            print(f"- {key}: {value}")
    if not has_constraints:
        print("- None")

    actions = state.get("schedule_actions") or []
    print("\nSchedule actions:")
    if not actions:
        print("- No schedule actions yet.")
    else:
        for index, action in enumerate(actions[-5:], start=max(1, len(actions) - 4)):
            selected = [
                str(course.get("course_code"))
                for course in action.get("selected_courses", [])
                if course.get("course_code")
            ]
            print(f"{index}. {action.get('user_message')}")
            print(f"   selected: {', '.join(selected) if selected else 'none'}")


def _patch_grounded_text_generation() -> None:
    import app.agent.langchain_agent as langchain_agent

    langchain_agent.generate_grounded_response = lambda **kwargs: kwargs["fallback"]


if __name__ == "__main__":
    main()

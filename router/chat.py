"""Interactive REPL for the hybrid router.

    python -m router.chat                       # interactive session
    python -m router.chat --ask "..."           # single-shot, prints JSON
    python -m router.chat --ask "..." --verbose # show timings + sources
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# sys.path bootstrap for direct invocation.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from router.router import build_default_router


def _print_response(resp, verbose: bool) -> None:
    print()
    print(f"[{resp.intent}  conf={resp.intent_confidence:.2f}  via={resp.intent_source}]")
    if resp.intent_reason:
        print(f"  reason: {resp.intent_reason}")
    if verbose:
        print(
            f"  timings: total={resp.elapsed_ms_total}ms "
            f"(cls={resp.elapsed_ms_classify} sql={resp.elapsed_ms_sql} "
            f"rag={resp.elapsed_ms_rag} synth={resp.elapsed_ms_synth})"
        )
        if resp.sql:
            print(f"  sql: {resp.sql}")
        if resp.sources:
            print(f"  sources: {', '.join(resp.sources[:5])}"
                  + (f" (+{len(resp.sources)-5} more)" if len(resp.sources) > 5 else ""))
        if resp.error:
            print(f"  error: {resp.error}")

    print()
    print(resp.answer_text or "(no answer)")
    print()


def _repl(router, verbose: bool) -> int:
    print("HCM hybrid analytics chat. Type 'help', 'reset', 'exit'.")
    print("Examples:")
    print("  - Which department has the highest attrition?")
    print("  - Tell me about our overall workforce health.")
    print("  - Why is Marketing attrition so high?")
    print()
    try:
        while True:
            try:
                q = input("hcm> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            lo = q.lower()
            if lo in ("exit", "quit", ":q"):
                break
            if lo == "help":
                print("Commands: help | reset | exit")
                continue
            if lo == "reset":
                router.reset_conversation()
                print("(conversation cleared)")
                continue
            resp = router.ask(q)
            _print_response(resp, verbose)
    finally:
        router.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="HCM hybrid analytics chat")
    p.add_argument("--ask", type=str, default=None,
                   help="Single-shot question; exits after one answer.")
    p.add_argument("--json", action="store_true",
                   help="With --ask, emit the full structured response as JSON.")
    p.add_argument("--verbose", action="store_true",
                   help="Show intent timings, generated SQL, and source IDs.")
    args = p.parse_args()

    router = build_default_router()

    if args.ask:
        resp = router.ask(args.ask)
        if args.json:
            print(json.dumps(resp.to_dict(), default=str, indent=2))
        else:
            _print_response(resp, args.verbose)
        router.close()
        return 0 if not resp.error else 1

    return _repl(router, args.verbose)


if __name__ == "__main__":
    sys.exit(main())

"""Unified `research` and `resume` CLI wrapper.

Examples:
    python -m scripts.research research "What is a transformer?" --hitl
    python -m scripts.research resume --thread-id demo --approve

The existing ``scripts.run_research`` command remains the implementation; this
module only exposes an explicit two-command interface for the product demo.
"""

from __future__ import annotations

import sys


def _usage() -> str:
    return (
        "Uso:\n"
        "  research research <pregunta> [opciones]\n"
        "  research resume --thread-id <id> [--approve|--reject] [opciones]\n"
        "\n"
        "Pasa --help después del subcomando para ver todas las opciones."
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(_usage())
        return 0
    command, rest = args[0], args[1:]
    if command not in {"research", "resume"}:
        print(f"Comando desconocido: {command}\n\n{_usage()}", file=sys.stderr)
        return 2
    forwarded = ["--resume", *rest] if command == "resume" else rest
    sys.argv = ["research", *forwarded]
    from scripts.run_research import main as run_main

    return run_main()


if __name__ == "__main__":
    raise SystemExit(main())

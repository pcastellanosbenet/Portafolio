"""Command-line entry point for the gateway."""

from __future__ import annotations

import argparse
import asyncio

from src.config import get_settings
from src.gateway.runner import build_gateway, run_http, run_stdio


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MCP gateway")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="http",
        help="Transport to serve (default: http)",
    )
    args = parser.parse_args()

    gateway = build_gateway(get_settings())
    if args.transport == "stdio":
        asyncio.run(run_stdio(gateway))
    else:
        asyncio.run(run_http(gateway))


if __name__ == "__main__":
    main()

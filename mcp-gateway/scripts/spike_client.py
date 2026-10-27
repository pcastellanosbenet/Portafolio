"""Phase 0 client checks for tools, resources, prompts, progress, MRTR and subscriptions."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.types import ElicitRequestParams, ElicitResult

ROOT = Path(__file__).resolve().parents[1]
SPIKE_SERVER = ROOT / "scripts" / "spike_server.py"


async def answer_elicitation(_context: Any, params: ElicitRequestParams) -> ElicitResult:
    """Approve every elicitation request during the spike."""
    print(f"  elicitation requested: {getattr(params, 'message', params)}")
    return ElicitResult(action="accept", content={"approve": True})


async def check_cancellation(client: Client) -> None:
    """Verify that a client timeout cancels the server-side handler."""
    marker = Path("/tmp/mcp-gateway-cancelled")
    marker.unlink(missing_ok=True)
    try:
        await client.call_tool("cancel_probe", {"seconds": 5}, read_timeout_seconds=0.5)
    except Exception as exc:  # noqa: BLE001 - the spike reports any timeout shape
        print(f"cancel_probe raised: {type(exc).__name__}")
    await asyncio.sleep(1)
    print(f"cancel marker written: {marker.exists()}")


async def check_client(client: Client, label: str) -> None:
    """Exercise every protocol primitive the gateway will depend on."""
    print(f"\n== {label} ==")
    print(f"protocol: {client.protocol_version}")
    print(f"server: {client.server_info}")

    tools = await client.list_tools()
    names = sorted(tool.name for tool in tools.tools)
    print(f"tools ({len(names)}): {', '.join(names)}")

    add = await client.call_tool("add", {"a": 2, "b": 3})
    print(f"add -> is_error={add.is_error} structured={add.structured_content}")

    resource = await client.read_resource("spike://info")
    print(f"resource -> {resource.contents[0].text}")

    prompt = await client.get_prompt("review", {"text": "hola"})
    print(f"prompt -> {prompt.messages[0].content.text[:40]!r}")

    progress: list[float] = []

    async def on_progress(value: float, total: float | None, message: str | None) -> None:
        progress.append(value)
        print(f"  progress {value}/{total}: {message}")

    slow = await client.call_tool(
        "slow_task", {"seconds": 0.2}, progress_callback=on_progress
    )
    print(f"slow_task -> {slow.structured_content} ({len(progress)} progress events)")

    approval = await client.call_tool("approve_action", {"action": "restart-api"})
    print(f"approve_action -> {approval.structured_content}")

    async with client.listen(tools_list_changed=True) as subscription:
        print(f"subscription honored: {subscription.honored}")
        call = asyncio.create_task(client.call_tool("refresh_tools"))
        try:
            async with asyncio.timeout(5):
                async for event in subscription:
                    print(f"  subscription event: {event}")
                    break
        finally:
            await call

    tools_after = await client.list_tools()
    print(f"tools after refresh: {len(tools_after.tools)}")

    await check_cancellation(client)


async def run_in_memory() -> None:
    """Run the spike against the server object without a transport."""
    sys.path.insert(0, str(ROOT))
    from scripts.spike_server import mcp

    async with Client(mcp, elicitation_callback=answer_elicitation) as client:
        await check_client(client, "in-memory")


async def run_stdio() -> None:
    """Run the spike against a real stdio subprocess."""
    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "bin" / "python"),
        args=[str(SPIKE_SERVER)],
        cwd=str(ROOT),
    )
    async with Client(params, elicitation_callback=answer_elicitation) as client:
        await check_client(client, "stdio")


async def run_url(url: str) -> None:
    """Run the spike against a Streamable HTTP endpoint."""
    async with Client(url, elicitation_callback=answer_elicitation) as client:
        await check_client(client, f"streamable-http {url}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Streamable HTTP endpoint to test")
    parser.add_argument("--stdio", action="store_true", help="Test a stdio subprocess")
    parser.add_argument("--memory", action="store_true", help="Test the in-memory server")
    args = parser.parse_args()

    if args.url:
        asyncio.run(run_url(args.url))
    elif args.stdio:
        asyncio.run(run_stdio())
    elif args.memory:
        asyncio.run(run_in_memory())
    else:
        parser.error("choose --memory, --stdio or --url")


if __name__ == "__main__":
    main()

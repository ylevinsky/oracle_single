import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    root = Path(__file__).resolve().parent.parent
    server = StdioServerParameters(
        command=str(root / "myoracle_mcp" / ".venv" / "Scripts" / "python.exe"),
        args=[str(root / "myoracle_mcp" / "server.py")],
        cwd=str(root),
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            prepared = await session.call_tool(
                "prepare_connection", {"connection_name": "es_db2_orclsp_sys"}
            )
            if prepared.isError or not prepared.structuredContent:
                raise RuntimeError(f"prepare_connection failed: {prepared}")
            payload = prepared.structuredContent.get(
                "result", prepared.structuredContent
            )
            result = await session.call_tool(
                "list_custom_jobs",
                {
                    "connection_name": "es_db2_orclsp_sys",
                    "confirmation_token": payload["confirmation_token"],
                },
            )
            if result.isError:
                raise RuntimeError(f"list_custom_jobs failed: {result}")
            print(json.dumps(result.structuredContent, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

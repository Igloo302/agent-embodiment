#!/usr/bin/env python3
"""
server.py — MCP stdio server for Agent Embodiment.
Exposes embodiment operations as MCP tools for any MCP client (Hermes, Claude Desktop, etc.).

Usage:
    python3 server.py                    # Start MCP server
    python3 server.py --list             # List available tools
    python3 server.py --call <tool> [params]  # Test a tool call

Architecture inspired by GBrain's contract-first MCP implementation.
"""

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: mcp package not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

from operations import (
    operations,
    get_operation,
    OperationError,
)


# --- Server Setup ---
app = Server("embodiment")


@app.list_tools()
async def list_tools() -> List[Tool]:
    """Generate tool definitions from operations."""
    tools = []
    for op in operations:
        # Build input schema from params
        properties = {}
        required = []
        
        for param_name, param_def in op["params"].items():
            prop = {"type": param_def["type"]}
            if param_def.get("description"):
                prop["description"] = param_def["description"]
            if param_def.get("enum"):
                prop["enum"] = param_def["enum"]
            properties[param_name] = prop
            
            if param_def.get("required"):
                required.append(param_name)
        
        tool = Tool(
            name=op["name"],
            description=op["description"],
            inputSchema={
                "type": "object",
                "properties": properties,
                "required": required
            }
        )
        tools.append(tool)
    
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> List[TextContent]:
    """Dispatch tool calls to operation handlers."""
    op = get_operation(name)
    if not op:
        return [TextContent(
            type="text",
            text=json.dumps({"error": "unknown_tool", "message": f"Unknown tool: {name}"})
        )]
    
    params = arguments or {}
    
    try:
        result = await op["handler"](params)
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False)
        )]
    except OperationError as e:
        return [TextContent(
            type="text",
            text=json.dumps(e.to_dict(), indent=2, ensure_ascii=False)
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "internal_error",
                "message": str(e)
            }, indent=2, ensure_ascii=False)
        )]


# --- CLI Commands ---

def list_tools_cli():
    """List all available tools (CLI mode)."""
    print("Agent Embodiment MCP Tools")
    print("=" * 50)
    for op in operations:
        print(f"\n📌 {op['name']}")
        print(f"   {op['description']}")
        if op["params"]:
            print("   Params:")
            for param_name, param_def in op["params"].items():
                required = " (required)" if param_def.get("required") else ""
                print(f"     - {param_name}: {param_def['type']}{required}")
                if param_def.get("description"):
                    print(f"       {param_def['description']}")


async def call_tool_cli(name: str, params_json: str):
    """Test a tool call (CLI mode)."""
    op = get_operation(name)
    if not op:
        print(f"Error: Unknown tool: {name}")
        print(f"Available tools: {', '.join(o['name'] for o in operations)}")
        sys.exit(1)
    
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON: {params_json}")
        sys.exit(1)
    
    try:
        result = await op["handler"](params)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except OperationError as e:
        print(json.dumps(e.to_dict(), indent=2, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


# --- Main ---

async def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "--list":
            list_tools_cli()
            return
        
        elif command == "--call":
            if len(sys.argv) < 3:
                print("Usage: server.py --call <tool_name> [params_json]")
                sys.exit(1)
            
            tool_name = sys.argv[2]
            params_json = sys.argv[3] if len(sys.argv) > 3 else "{}"
            await call_tool_cli(tool_name, params_json)
            return
        
        elif command == "--help":
            print(__doc__)
            return
        
        else:
            print(f"Unknown command: {command}")
            print("Use --help for usage info")
            sys.exit(1)
    
    # Start MCP server
    print("Starting Agent Embodiment MCP server (stdio)...", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

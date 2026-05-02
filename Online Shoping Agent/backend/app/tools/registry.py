"""Tool registry — maps tool names to async callables."""
from app.graph.nodes.tools.product_tool import product_detail_tool
from app.graph.nodes.tools.search_tool import search_tool

TOOL_REGISTRY = {
    "product_detail": product_detail_tool,
    "search_tool": search_tool,
}


async def call_tool(tool_name: str, **kwargs):
    """Dispatch a tool call by name."""
    handler = TOOL_REGISTRY.get(tool_name)
    if not handler:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}
    return await handler(**kwargs)

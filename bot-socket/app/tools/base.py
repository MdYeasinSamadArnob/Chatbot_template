"""
Convenience re-export of the @register_tool decorator.

Usage in tool modules:
    from app.tools.base import register_tool

    @register_tool("my_tool", "description", MyInputSchema)
    async def my_tool(args: MyInputSchema, memory=None) -> str:
        ...
"""

from app.tools.registry import registry


def register_tool(name: str, description: str, schema):
    """
    Decorator that registers a function with the global ToolRegistry.

    Mirrors Metabase's deftool macro / tool metadata pattern, providing:
    - name     → :tool-name in Metabase
    - description → :doc in Metabase
    - schema   → Malli schema in Metabase (Pydantic here)
    """
    return registry.register(name, description, schema)

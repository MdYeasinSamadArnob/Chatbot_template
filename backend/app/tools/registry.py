"""
Tool registry — a lightweight singleton that stores all registered tools.

Mirrors Metabase's tools.clj which collects all tool vars by namespace,
but uses a simple dict keyed by tool name instead.

Usage:
    from app.tools.registry import registry

    @registry.register("my_tool", "Does something useful", MyInputSchema)
    async def my_tool(args: MyInputSchema, memory=None) -> str:
        ...
"""

from __future__ import annotations

from typing import Any, Callable, Type

from pydantic import BaseModel


class ToolDefinition:
    """
    Wraps a tool function with its metadata.

    Analogous to Metabase's Clojure tool vars with :tool-name, :schema metadata.
    """

    def __init__(
        self,
        name: str,
        description: str,
        schema: Type[BaseModel],
        fn: Callable,
    ) -> None:
        self.name = name
        self.description = description
        self.schema = schema
        self.fn = fn

    def to_openai_tool(self) -> dict[str, Any]:
        """
        Convert to the OpenAI function-calling format that litellm expects.
        The JSON schema is auto-generated from the Pydantic model.
        """
        raw_schema = self.schema.model_json_schema()
        # Remove the title field — LLMs handle it better without it
        raw_schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": raw_schema,
            },
        }

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r}>"


class ToolRegistry:
    """
    Global singleton registry for all tools.

    Mimics Metabase's profile-scoped tool lists:
        profile.get_tools() → ToolRegistry.get_for_profile(tool_names)
    """

    _instance: "ToolRegistry | None" = None
    _tools: dict[str, ToolDefinition]

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(
        self,
        name: str,
        description: str,
        schema: Type[BaseModel],
    ) -> Callable:
        """Decorator factory — registers the decorated function as a tool."""

        def decorator(fn: Callable) -> Callable:
            self._tools[name] = ToolDefinition(name, description, schema, fn)
            return fn

        return decorator

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def get_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_by_names(self, names: list[str]) -> list[ToolDefinition]:
        return [self._tools[n] for n in names if n in self._tools]

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


# Singleton instance — import this everywhere
registry = ToolRegistry()

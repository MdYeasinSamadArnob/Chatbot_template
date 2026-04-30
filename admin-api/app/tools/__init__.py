"""
Tool auto-registration.

Importing this package triggers all tool modules, which run their
@register_tool decorators and populate the global ToolRegistry.

To add a new tool:
  1. Create app/tools/my_tool.py with @register_tool(...)
  2. Add: from app.tools import my_tool  (below)
  3. Done — it will appear in all profiles that use all tools.
"""

from app.tools import calculator, datetime_tool, web_search, vector_search  # noqa: F401

__all__ = ["calculator", "datetime_tool", "web_search", "vector_search"]

"""
Agent profiles — configure different behaviour modes.

Mirrors Metabase's register-profile! / profiles.clj pattern:
  - Each profile selects a tool subset (None = all tools)
  - Sets max_iterations and temperature
  - Can inject extra system instructions

Add new profiles at the bottom of this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.tools.registry import ToolDefinition, registry


@dataclass
class AgentProfile:
    """
    Defines a named agent configuration.

    Analogous to Metabase's profile maps:
      {:name :internal :tools [...] :max-iterations 10 :temperature 0.3}
    """

    name: str
    description: str
    max_iterations: int = 10
    temperature: float = 0.3
    # None  → give the agent ALL registered tools
    # []    → give the agent NO tools (plain chat)
    # [...] → give the agent only the named tools
    tool_names: list[str] | None = None
    extra_instructions: str = ""

    def get_tools(self) -> list[ToolDefinition]:
        """Resolve tool names to ToolDefinition objects at call time."""
        if self.tool_names is None:
            return registry.get_all()
        if not self.tool_names:
            return []
        return registry.get_by_names(self.tool_names)


# ── Profile registry ───────────────────────────────────────────────────────

_profiles: dict[str, AgentProfile] = {}


def register_profile(profile: AgentProfile) -> None:
    _profiles[profile.name] = profile


def get_profile(name: str) -> AgentProfile:
    """Return the named profile, falling back to 'default'."""
    return _profiles.get(name, _profiles["default"])


def list_profiles() -> list[dict]:
    return [
        {"name": p.name, "description": p.description, "tool_names": p.tool_names}
        for p in _profiles.values()
    ]


# ── Built-in profiles ──────────────────────────────────────────────────────

register_profile(
    AgentProfile(
        name="default",
        description="General-purpose assistant with access to all tools.",
        max_iterations=10,
        temperature=0.3,
        tool_names=None,  # All tools
    )
)

register_profile(
    AgentProfile(
        name="assistant",
        description="Conversational assistant — no tools, just chat.",
        max_iterations=3,
        temperature=0.7,
        tool_names=[],  # No tools
        extra_instructions=(
            "You are a friendly conversational assistant. "
            "Answer directly from your knowledge."
        ),
    )
)

register_profile(
    AgentProfile(
        name="calculator",
        description="Math-focused agent — uses the calculate tool only.",
        max_iterations=5,
        temperature=0.1,
        tool_names=["calculate"],
        extra_instructions=(
            "You are a precise math assistant. "
            "Always use the calculate tool for arithmetic."
        ),
    )
)

register_profile(
    AgentProfile(
        name="researcher",
        description="Research agent — can search the web and calculate.",
        max_iterations=8,
        temperature=0.4,
        tool_names=["web_search", "calculate", "get_current_time"],
        extra_instructions=(
            "You are a research assistant. "
            "Search for up-to-date information when needed. "
            "Cite sources and be thorough."
        ),
    )
)

register_profile(
    AgentProfile(
        name="banking",
        description="Bank Help & Support assistant with RAG knowledge base access.",
        max_iterations=4,
        temperature=0.2,
        tool_names=["search_banking_knowledge", "calculate", "get_current_time"],
        extra_instructions=(
            "You are a helpful, professional banking support assistant. "
            "Always search the knowledge base FIRST before answering any banking question. "
            "Present answers as clear numbered steps when describing a process. "
            "Include any inline images exactly as returned by search results (they appear as markdown images). "
            "Keep answers factual, concise and friendly. "
            "If you cannot find the answer, politely direct the user to call the bank helpline."
        ),
    )
)

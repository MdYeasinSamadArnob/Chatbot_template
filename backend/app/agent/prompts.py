"""
System prompt builder — mirrors Metabase's agent/prompts.clj.

Metabase uses Selmer templates. We use f-strings with a base template
and profile-specific injections. Extend SYSTEM_PROMPT_TEMPLATE to add
new context variables (user capabilities, database info, etc.).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent.profiles import AgentProfile


SYSTEM_PROMPT_TEMPLATE = """\
You are a helpful AI assistant with a friendly, natural conversational style.

Current date/time (UTC): {current_time}

{profile_section}
{capabilities_section}
{long_term_section}
## Guidelines
- Be concise and direct. Prefer short paragraphs over walls of text.
- Use tools when they would give a better answer than your training data.
- After receiving a tool result, synthesize it into a clear, natural response.
- If you are unsure, say so — don't fabricate facts.
- Format numbers, code, and structured data clearly.
- For multi-step problems, think step by step before answering.
"""

BANKING_SYSTEM_PROMPT_TEMPLATE = """\
You are a professional and friendly {bank_name} Help & Support Assistant.
You help customers with banking questions, procedures, and guidance.

Current date/time (UTC): {current_time}

{profile_section}
{long_term_section}
## How to Answer
- ALWAYS call `search_banking_knowledge` first for any banking question before answering.
- Only call tools that are explicitly provided. NEVER invent or fabricate tool names — only `search_banking_knowledge`, `calculate`, and `get_current_time` exist.
- If the tool result says the knowledge base is "unavailable" or "not ready", do NOT retry it. Answer immediately using your general banking knowledge.
- Structure procedural answers as numbered steps (e.g., 1. Open the app, 2. Tap 'Transfers'…).
- If the knowledge base result includes images (markdown `![...](...)`), include them inline in your answer exactly as-is.
- Keep answers factual, concise, and easy to understand on a mobile screen.
- Do NOT speculate or make up banking procedures.
- If you cannot find a reliable answer, say: "Please contact {bank_name} support at our helpline for further assistance."
- Do not discuss competitor banks or give financial advice.
"""


def build_system_prompt(
    profile: AgentProfile,
    context: dict,
    long_term_memories: list[str] | None = None,
) -> str:
    """
    Build the full system prompt for an agent iteration.

    Args:
        profile: The active agent profile (sets instructions + tool subset).
        context: Request context dict (capabilities, user info, etc.).
        long_term_memories: Optional relevant memories from LTM search.
    """
    from app.config import settings

    current_time = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Profile-specific instructions section
    if profile.extra_instructions:
        profile_section = f"## Role\n{profile.extra_instructions}\n"
    else:
        profile_section = ""

    # Long-term memory section (recalled cross-session facts)
    if long_term_memories:
        mem_lines = "\n".join(f"  - {m}" for m in long_term_memories if m.strip())
        long_term_section = f"## Remembered Facts (from previous conversations)\n{mem_lines}\n"
    else:
        long_term_section = ""

    # Banking profile uses a dedicated, tighter template
    if profile.name == "banking":
        return BANKING_SYSTEM_PROMPT_TEMPLATE.format(
            bank_name=settings.bank_name,
            current_time=current_time,
            profile_section=profile_section,
            long_term_section=long_term_section,
        ).strip()

    # Capabilities section (user-supplied capabilities list)
    caps = context.get("capabilities", [])
    if caps:
        caps_list = "\n".join(f"  - {c}" for c in caps)
        capabilities_section = f"## Available Capabilities\n{caps_list}\n"
    else:
        capabilities_section = ""

    return SYSTEM_PROMPT_TEMPLATE.format(
        current_time=current_time,
        profile_section=profile_section,
        capabilities_section=capabilities_section,
        long_term_section=long_term_section,
    ).strip()

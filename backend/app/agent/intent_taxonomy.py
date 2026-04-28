"""
Intent taxonomy for the banking chatbot.

Each IntentDefinition maps a user intent to:
  - which agent profile handles it
  - whether a conversational flow should be activated
  - what quick-reply chips to surface on match
  - few-shot examples used by the classifier
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IntentDefinition:
    name: str
    display_name: str
    description: str
    profile: str = "banking"
    flow_name: Optional[str] = None
    required_slots: list[str] = field(default_factory=list)
    suggested_actions: list[dict] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


INTENTS: dict[str, IntentDefinition] = {
    "download_statement": IntentDefinition(
        name="download_statement",
        display_name="Download Statement",
        description="User wants to download, view, or get their bank, account, or transaction statement",
        profile="banking",
        flow_name="download_statement",
        required_slots=["date_range", "statement_type"],
        suggested_actions=[
            {"label": "Last 30 days", "value": "last 30 days"},
            {"label": "Last 90 days", "value": "last 90 days"},
            {"label": "Custom range", "value": "custom range"},
        ],
        examples=[
            "show me my statement",
            "download statement",
            "I need my transaction history",
            "get my account statement",
            "statement download",
            "আমার স্টেটমেন্ট দেখাও",
            "show my bank statement",
        ],
    ),
    "money_transfer": IntentDefinition(
        name="money_transfer",
        display_name="Transfer Money",
        description="User wants to transfer money to another account or person, or ask about transfer limits and procedures",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "How to transfer", "value": "how do I transfer money?"},
            {"label": "Transfer limits", "value": "what are my transfer limits?"},
            {"label": "International transfer", "value": "how do I send money internationally?"},
        ],
        examples=[
            "transfer money",
            "send money",
            "pay someone",
            "টাকা পাঠাতে চাই",
            "how to transfer",
            "wire transfer",
        ],
    ),
    "check_balance": IntentDefinition(
        name="check_balance",
        display_name="Check Balance",
        description="User wants to check their account balance or available funds",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "Check via app", "value": "how do I check my balance on the app?"},
            {"label": "Check via ATM", "value": "how do I check balance at ATM?"},
        ],
        examples=[
            "check balance",
            "what is my balance",
            "ব্যালেন্স দেখাও",
            "account balance",
            "how much money do I have",
        ],
    ),
    "card_services": IntentDefinition(
        name="card_services",
        display_name="Card Services",
        description="User wants to block, replace, activate, or get information about their debit or credit card",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "Block my card", "value": "how do I block my card?"},
            {"label": "Replace my card", "value": "how do I get a replacement card?"},
            {"label": "Card activation", "value": "how do I activate my new card?"},
        ],
        examples=[
            "block my card",
            "lost card",
            "card not working",
            "replace card",
            "কার্ড ব্লক করতে চাই",
            "stolen card",
            "activate my card",
        ],
    ),
    "loan_inquiry": IntentDefinition(
        name="loan_inquiry",
        display_name="Loan Inquiry",
        description="User asks about loan products, eligibility criteria, application process, or EMI calculations",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "Loan eligibility", "value": "what are the loan eligibility requirements?"},
            {"label": "Apply for loan", "value": "how do I apply for a loan?"},
            {"label": "Calculate EMI", "value": "how do I calculate my loan EMI?"},
        ],
        examples=[
            "loan",
            "personal loan",
            "home loan",
            "ঋণ",
            "credit",
            "EMI",
            "বন্ধক",
        ],
    ),
    "complaint": IntentDefinition(
        name="complaint",
        display_name="Complaint or Issue",
        description="User has a complaint, experienced a problem, or wants to report an issue with the bank or its services",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "Speak to an agent", "value": "I want to speak to a human support agent"},
            {"label": "Report an issue", "value": "I want to report a specific issue"},
        ],
        examples=[
            "complaint",
            "problem",
            "issue",
            "not working",
            "wrong charge",
            "অভিযোগ",
            "charged incorrectly",
            "money deducted",
        ],
    ),
    "escalation_request": IntentDefinition(
        name="escalation_request",
        display_name="Human Agent Request",
        description="User explicitly wants to speak to a human, customer service agent, or support representative",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "Yes, connect me", "value": "yes please connect me to an agent"},
            {"label": "Continue with bot", "value": "no, I will continue here"},
        ],
        examples=[
            "speak to human",
            "speak to agent",
            "real person",
            "customer service",
            "helpline",
            "মানুষের সাথে কথা বলতে চাই",
            "support agent",
            "talk to someone",
        ],
    ),
    "account_services": IntentDefinition(
        name="account_services",
        display_name="Account Services",
        description="User asks about opening, closing, or updating their bank account, or account-related services",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "Open an account", "value": "how do I open a new bank account?"},
            {"label": "Update my details", "value": "how do I update my personal details?"},
        ],
        examples=[
            "open account",
            "new account",
            "update details",
            "change address",
            "account opening",
            "একাউন্ট খুলতে চাই",
        ],
    ),
    "general_faq": IntentDefinition(
        name="general_faq",
        display_name="General FAQ",
        description="General banking questions, information requests, FAQs, or queries that don't fit other categories",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[],
        examples=[
            "how does",
            "what is",
            "tell me about",
            "information",
            "explain",
        ],
    ),
    "greeting": IntentDefinition(
        name="greeting",
        display_name="Greeting",
        description="Simple greeting, introduction, or small talk to start the conversation",
        profile="banking",
        flow_name=None,
        required_slots=[],
        suggested_actions=[
            {"label": "Check my balance", "value": "How do I check my balance?"},
            {"label": "Download statement", "value": "I want to download my statement"},
            {"label": "Transfer money", "value": "How do I transfer money?"},
            {"label": "Card services", "value": "I need help with my card"},
        ],
        examples=[
            "hi",
            "hello",
            "hey",
            "good morning",
            "হ্যালো",
            "হ্যাই",
            "আস্সালামু আলাইকুম",
        ],
    ),
}

# Used when classification fails or confidence is too low
FALLBACK_INTENT = INTENTS["general_faq"]

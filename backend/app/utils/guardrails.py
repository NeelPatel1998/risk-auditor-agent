"""
Input guardrails for an enterprise banking AI assistant.

Layers (in order):
  1. Length / empty
  2. PII detection  — hard block, fixed response
  3. Prompt injection — hard block, fixed response
  4. Role-escalation / jailbreak — hard block, fixed response
  5. Sensitive financial data patterns — hard block
  6. Vagueness / filler — soft redirect
"""

import re

# ---------------------------------------------------------------------------
# Fixed responses — never echo user content that may contain sensitive data
# ---------------------------------------------------------------------------

PII_RESPONSE = (
    "I can't process messages that appear to contain personal or sensitive identifying information "
    "(e.g. ID numbers, payment card numbers, account numbers, email addresses, or phone numbers). "
    "Please remove or redact that information and rephrase your question about the document."
)

INJECTION_RESPONSE = (
    "I'm a document analysis assistant for risk management documents. "
    "I'm not able to change my role, ignore my instructions, or act outside that scope. "
    "Please ask a question about your uploaded document."
)

JAILBREAK_RESPONSE = (
    "That request falls outside what I'm designed to do. "
    "I'm here to help you analyze uploaded risk and regulatory documents. "
    "How can I help with your document?"
)

SENSITIVE_DATA_RESPONSE = (
    "I'm not able to process messages containing what appear to be financial account identifiers, "
    "routing numbers, or similar sensitive banking data. "
    "Please ask a general question about the document content."
)

VAGUE_RESPONSE = (
    "That question is too brief or general for me to answer reliably from the document. "
    "Please ask something specific — for example, what a section requires, "
    "how two topics relate, or what definitions appear in the text."
)

# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

# US/CA Social Security / Social Insurance Number
_SSN_SIN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
# Email addresses
_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# North-American phone numbers
_PHONE_NA = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
# Payment card (4×4 digit groups)
_CARD_LIKE = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b")
# Canadian SIN (9 digits, may have spaces/dashes)
_CA_SIN = re.compile(r"\b\d{3}[-\s]\d{3}[-\s]\d{3}\b")
# Passport-style alphanumeric IDs
_PASSPORT = re.compile(r"\b[A-Z]{1,2}\d{6,9}\b")


def _has_pii(text: str) -> bool:
    return any(
        p.search(text)
        for p in (_SSN_SIN, _EMAIL, _PHONE_NA, _CARD_LIKE, _CA_SIN, _PASSPORT)
    )


# ---------------------------------------------------------------------------
# Sensitive financial data patterns
# ---------------------------------------------------------------------------

# Bank account numbers (8–18 digits, standalone)
_ACCOUNT_NUM = re.compile(r"\b\d{8,18}\b")
# ABA routing number (exactly 9 digits)
_ROUTING_NUM = re.compile(r"\b\d{9}\b")
# Canadian transit/institution codes (XXXXX-YYY or similar)
_CA_TRANSIT = re.compile(r"\b\d{5}-\d{3}\b")
# SWIFT/BIC codes
_SWIFT = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
# IBAN patterns
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]{0,16})?\b")


def _has_sensitive_financial(text: str) -> bool:
    return any(p.search(text) for p in (_CA_TRANSIT, _SWIFT, _IBAN))


# ---------------------------------------------------------------------------
# Prompt injection patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(?:previous|above|prior|earlier)\s+(?:instructions?|prompts?|context|rules?|constraints?)",
    r"disregard\s+(?:your\s+)?(?:instructions?|prompt|guidelines?|rules?)",
    r"forget\s+(?:everything|all|your|previous)",
    r"override\s+(?:your\s+)?(?:instructions?|guidelines?|rules?|constraints?|safety)",
    r"bypass\s+(?:your\s+)?(?:filters?|restrictions?|rules?|guidelines?|safety)",
    r"new\s+(?:instructions?|prompt|system\s+prompt|rules?|directives?)",
    r"system\s*prompt",
    r"initial\s+prompt",
    r"original\s+instructions?",
    r"you\s+are\s+now\s+(?:a|an|in\s+developer)",
    r"your\s+(?:true|real|actual)\s+(?:instructions?|purpose|role|goal)",
    r"what\s+(?:are\s+)?your\s+(?:exact\s+)?instructions?",
    r"reveal\s+(?:your\s+)?(?:prompt|instructions?|system|training)",
    r"show\s+(?:me\s+)?(?:your\s+)?(?:prompt|instructions?|system\s+message)",
    r"output\s+(?:your\s+)?(?:prompt|instructions?|initial|system)",
    r"print\s+(?:your\s+)?(?:prompt|instructions?)",
]

_INJECTION_RE = re.compile(
    "|".join(_INJECTION_PATTERNS),
    re.IGNORECASE | re.DOTALL,
)


def check_injection(text: str) -> bool:
    """Return True if the text appears to be a prompt injection attempt."""
    return bool(_INJECTION_RE.search(text))


# ---------------------------------------------------------------------------
# Role escalation / jailbreak patterns
# ---------------------------------------------------------------------------

_JAILBREAK_PATTERNS = [
    r"jailbreak",
    r"dan\s+mode",
    r"developer\s+mode",
    r"god\s+mode",
    r"unrestricted\s+mode",
    r"pretend\s+(?:you\s+are|to\s+be|you're|you\s+have\s+no)",
    r"act\s+as\s+(?:a|an|if)\s+(?!a\s+(?:risk|compliance|regulatory))",  # allow "act as a risk expert"
    r"role[\s\-]?play\s+as",
    r"simulate\s+(?:a|an|being)",
    r"you\s+(?:have\s+no|don'?t\s+have)\s+(?:any\s+)?(?:restrictions?|rules?|guidelines?|filters?|limits?)",
    r"no\s+(?:content\s+)?(?:filter|restriction|rule|limit|guideline)s?",
    r"do\s+anything\s+(?:now|i\s+say)",
    r"harmful\s+(?:content|instructions?|advice)",
    r"illegal\s+(?:activity|advice|instructions?)",
    r"without\s+(?:any\s+)?(?:ethical\s+)?(?:restrictions?|constraints?|limits?|filters?)",
]

_JAILBREAK_RE = re.compile(
    "|".join(_JAILBREAK_PATTERNS),
    re.IGNORECASE | re.DOTALL,
)


def check_jailbreak(text: str) -> bool:
    """Return True if the text attempts role escalation or jailbreak."""
    return bool(_JAILBREAK_RE.search(text))


# ---------------------------------------------------------------------------
# Vagueness / filler
# ---------------------------------------------------------------------------

_GENERIC_ONLY = re.compile(
    r"^\s*(?:hi+|hello|hey|thanks+|thank\s+you|ok+|okay|yes|no|sure|yep|nope|good|great|cool)\s*[!.]?\s*$",
    re.IGNORECASE,
)

_VAGUE_CHATTER = re.compile(
    r"^\s*(?:tell\s+me\s+more|what\s+else|anything\s+else|go\s+on|more\s+info|elaborate|explain\s+that)\s*[?.!]?\s*$",
    re.IGNORECASE,
)

_QUESTION_HINT = re.compile(
    r"\b(what|how|why|when|where|which|who|summarize|summarise|explain|list|describe|compare|"
    r"does|is|are|define|outline|identify|name|require|expect|mandate|state|specify|address)\b",
    re.IGNORECASE,
)


def _is_vague(text: str) -> bool:
    s = text.strip()
    # Only block truly empty/noise inputs. Short but valid questions (e.g. "Define MRM?",
    # "What is SR 11-7?") are 10–16 chars and should reach the model.
    if len(s) < 4:
        return True
    if _GENERIC_ONLY.match(s):
        return True
    if _VAGUE_CHATTER.match(s):
        return True
    words = s.split()
    if len(words) <= 3 and len(s) < 36 and "?" not in s and not _QUESTION_HINT.search(s):
        return True
    return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def guard_user_message(message: str) -> str | None:
    """
    Run all guardrail layers against a user message.

    Returns a fixed assistant reply string if the message should be blocked,
    or None if it is safe to proceed with RAG.

    Layer order:
      1. Empty / length check
      2. PII detection
      3. Prompt injection
      4. Role escalation / jailbreak
      5. Sensitive financial data
      6. Vagueness
    """
    s = message.strip()

    if len(s) < 1:
        return VAGUE_RESPONSE

    if _has_pii(s):
        return PII_RESPONSE

    if check_injection(s):
        return INJECTION_RESPONSE

    if check_jailbreak(s):
        return JAILBREAK_RESPONSE

    if _has_sensitive_financial(s):
        return SENSITIVE_DATA_RESPONSE

    if _is_vague(s):
        return VAGUE_RESPONSE

    return None

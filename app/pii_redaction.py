"""
PII Redaction Module for AAM

Removes or masks personally identifiable information from observations
before they are processed by the inference engine.

Supports:
- Email addresses
- Phone numbers
- Social Security Numbers (SSN)
- Credit card numbers
- IP addresses
- Common PII field names (name, address, etc.)
"""
import re
from typing import Any, Dict, List, Optional
from copy import deepcopy


# Regex patterns for PII detection
PII_PATTERNS = {
    "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "phone": re.compile(r'\b(?:\+?1[-.]?)?\(?[0-9]{3}\)?[-.]?[0-9]{3}[-.]?[0-9]{4}\b'),
    "ssn": re.compile(r'\b\d{3}[-]?\d{2}[-]?\d{4}\b'),
    "credit_card": re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
    "ip_address": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
}

# Field names that commonly contain PII
PII_FIELD_NAMES = {
    "email", "e_mail", "email_address", "emailaddress",
    "phone", "phone_number", "phonenumber", "mobile", "cell",
    "ssn", "social_security", "social_security_number",
    "credit_card", "creditcard", "card_number", "cardnumber",
    "first_name", "firstname", "last_name", "lastname", "full_name", "fullname", "name",
    "address", "street", "street_address", "home_address", "mailing_address",
    "city", "state", "zip", "zipcode", "zip_code", "postal_code",
    "dob", "date_of_birth", "birthdate", "birth_date",
    "password", "passwd", "pwd", "secret", "api_key", "apikey", "token",
    "driver_license", "drivers_license", "license_number",
    "passport", "passport_number",
    "bank_account", "account_number", "routing_number",
    "ip", "ip_address", "ipaddress",
    "personal_id", "national_id", "tax_id",
}

# Redaction placeholder
REDACTED = "[REDACTED]"


def redact_string_value(value: str) -> str:
    """
    Redact PII patterns from a string value.

    Args:
        value: String that may contain PII

    Returns:
        String with PII patterns replaced with [REDACTED]
    """
    if not isinstance(value, str):
        return value

    redacted = value
    for pattern_name, pattern in PII_PATTERNS.items():
        redacted = pattern.sub(REDACTED, redacted)

    return redacted


def is_pii_field(field_name: str) -> bool:
    """
    Check if a field name indicates PII content.

    Args:
        field_name: Name of the field to check

    Returns:
        True if field name suggests PII content
    """
    if not field_name:
        return False

    normalized = field_name.lower().replace("-", "_").replace(" ", "_")
    return normalized in PII_FIELD_NAMES


def redact_dict(data: Dict[str, Any], redact_values: bool = True) -> Dict[str, Any]:
    """
    Recursively redact PII from a dictionary.

    Args:
        data: Dictionary that may contain PII
        redact_values: If True, also scan string values for PII patterns

    Returns:
        Dictionary with PII redacted
    """
    if not isinstance(data, dict):
        return data

    redacted = {}
    for key, value in data.items():
        # Check if field name indicates PII
        if is_pii_field(key):
            redacted[key] = REDACTED
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value, redact_values)
        elif isinstance(value, list):
            redacted[key] = redact_list(value, redact_values)
        elif isinstance(value, str) and redact_values:
            redacted[key] = redact_string_value(value)
        else:
            redacted[key] = value

    return redacted


def redact_list(data: List[Any], redact_values: bool = True) -> List[Any]:
    """
    Recursively redact PII from a list.

    Args:
        data: List that may contain PII
        redact_values: If True, also scan string values for PII patterns

    Returns:
        List with PII redacted
    """
    if not isinstance(data, list):
        return data

    redacted = []
    for item in data:
        if isinstance(item, dict):
            redacted.append(redact_dict(item, redact_values))
        elif isinstance(item, list):
            redacted.append(redact_list(item, redact_values))
        elif isinstance(item, str) and redact_values:
            redacted.append(redact_string_value(item))
        else:
            redacted.append(item)

    return redacted


def redact_pii_from_observation(observation: Dict[str, Any], policy: str = "required") -> Dict[str, Any]:
    """
    Redact PII from an observation based on governance policy.

    This is the main entry point for PII redaction in AAM.
    Called before observations are processed by the inference engine.

    Args:
        observation: Raw observation from a collector
        policy: PII redaction policy - "required", "optional", or "disabled"

    Returns:
        Observation with PII redacted (if policy requires it)
    """
    if policy == "disabled":
        return observation

    if policy == "optional":
        # In optional mode, only redact if observation has sensitive flag
        if not observation.get("metadata", {}).get("contains_pii", False):
            return observation

    # Deep copy to avoid modifying original
    redacted_obs = deepcopy(observation)

    # Redact endpoint_info (may contain credentials, IPs, etc.)
    if "endpoint_info" in redacted_obs:
        redacted_obs["endpoint_info"] = redact_dict(redacted_obs["endpoint_info"])

    # Redact schema_sample (may contain actual data samples)
    if "schema_sample" in redacted_obs and redacted_obs["schema_sample"]:
        redacted_obs["schema_sample"] = redact_dict(redacted_obs["schema_sample"])

    # Redact metadata
    if "metadata" in redacted_obs:
        redacted_obs["metadata"] = redact_dict(redacted_obs["metadata"])

    # Redact entity_hints (may contain names, etc.)
    if "entity_hints" in redacted_obs and isinstance(redacted_obs["entity_hints"], list):
        redacted_obs["entity_hints"] = [
            redact_string_value(hint) if isinstance(hint, str) else hint
            for hint in redacted_obs["entity_hints"]
        ]

    # Mark observation as redacted
    if "metadata" not in redacted_obs:
        redacted_obs["metadata"] = {}
    redacted_obs["metadata"]["pii_redacted"] = True
    redacted_obs["metadata"]["redaction_policy"] = policy

    return redacted_obs


def get_redaction_stats(observation: Dict[str, Any], redacted_observation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate statistics about what was redacted.

    Args:
        observation: Original observation
        redacted_observation: Observation after redaction

    Returns:
        Dictionary with redaction statistics
    """
    def count_redacted(data: Any) -> int:
        """Count occurrences of [REDACTED] in data structure."""
        if isinstance(data, str):
            return data.count(REDACTED)
        elif isinstance(data, dict):
            return sum(count_redacted(v) for v in data.values())
        elif isinstance(data, list):
            return sum(count_redacted(item) for item in data)
        return 0

    original_str = str(observation)
    redacted_str = str(redacted_observation)

    return {
        "fields_redacted": count_redacted(redacted_observation),
        "original_length": len(original_str),
        "redacted_length": len(redacted_str),
        "reduction_pct": round((1 - len(redacted_str) / len(original_str)) * 100, 2) if original_str else 0
    }

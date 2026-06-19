"""
validators.py
--------------
Pure, stateless validation functions used by the Xeno Transaction
Validation Platform. Kept separate from the Streamlit UI layer so the
logic can be unit-tested and reused (e.g. behind an API) without any
UI dependency.

Design principle: every validator takes plain Python / pandas inputs
and returns a structured result (bool / cleaned value / reason string)
rather than raising, so the caller can keep processing the rest of the
row even when one field fails.
"""

from __future__ import annotations
import re
import pandas as pd
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List

# --------------------------------------------------------------------------
# Phone validation
# --------------------------------------------------------------------------

_NON_DIGIT_RE = re.compile(r"[^\d]")


def clean_phone(raw: Any) -> str:
    """Strip spaces, dashes, parentheses, and a leading country dial code
    if present, returning only the local digit string."""
    if pd.isna(raw):
        return ""
    s = str(raw).strip()
    # Drop a leading + and any non-digits (spaces, dashes, brackets)
    s = s.replace(" ", "")
    digits = _NON_DIGIT_RE.sub("", s)
    return digits


def validate_phone(raw_phone: Any, country_code: Any,
                    country_rules: Dict[str, Dict]) -> Tuple[bool, str, str]:
    """
    Returns (is_valid, normalized_phone, reason).

    - country_code is matched case-insensitively against country_rules keys
      (e.g. 'IN', 'SG').
    - If the country isn't in the configured rule set, the row is flagged
      rather than silently passed, so new countries must be added
      explicitly (configurable, not hard-coded).
    """
    digits = clean_phone(raw_phone)
    if not digits:
        return False, "", "Phone number is missing/empty"

    cc = str(country_code).strip().upper() if pd.notna(country_code) else ""
    rule = country_rules.get(cc)
    if rule is None:
        return False, digits, f"No phone rule configured for country '{cc or 'UNKNOWN'}'"

    expected_len = rule["length"]
    dial_code_digits = _NON_DIGIT_RE.sub("", rule.get("dial_code", ""))

    # If the dial code is embedded in the number (e.g. 91XXXXXXXXXX), strip it
    if dial_code_digits and digits.startswith(dial_code_digits) and \
       len(digits) == expected_len + len(dial_code_digits):
        digits = digits[len(dial_code_digits):]

    if len(digits) != expected_len:
        return False, digits, (
            f"Expected {expected_len} digits for {rule.get('name', cc)}, got {len(digits)}"
        )
    if not digits.isdigit():
        return False, digits, "Phone number contains non-numeric characters"

    return True, digits, ""


# --------------------------------------------------------------------------
# Date validation
# --------------------------------------------------------------------------

# Ordered by specificity so the detector tries the most distinctive formats first.
CANDIDATE_DATE_FORMATS: List[str] = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
]


def detect_date_format(sample_values: List[str], min_match_ratio: float = 0.85) -> Optional[str]:
    """Try each candidate format against a sample of values and return the
    first format that successfully parses at least `min_match_ratio` of the
    non-empty sample. Returns None if no format reaches the threshold."""
    non_empty = [str(v).strip() for v in sample_values if pd.notna(v) and str(v).strip()]
    if not non_empty:
        return None

    best_fmt, best_ratio = None, 0.0
    for fmt in CANDIDATE_DATE_FORMATS:
        hits = 0
        for v in non_empty:
            try:
                datetime.strptime(v, fmt)
                hits += 1
            except ValueError:
                pass
        ratio = hits / len(non_empty)
        if ratio > best_ratio:
            best_ratio, best_fmt = ratio, fmt
        if ratio >= min_match_ratio:
            return fmt
    return best_fmt if best_ratio >= min_match_ratio else None


def validate_date(raw_value: Any, expected_format: str) -> Tuple[bool, str, str]:
    """Returns (is_valid, normalized_iso_string, reason)."""
    if pd.isna(raw_value) or str(raw_value).strip() == "":
        return False, "", "Date is missing/empty"
    s = str(raw_value).strip()
    try:
        dt = datetime.strptime(s, expected_format)
    except ValueError:
        return False, "", f"Does not match expected format '{expected_format}'"

    # Reject obviously implausible dates (e.g. far-future signups from typos)
    if dt.year < 2000 or dt.year > datetime.now().year + 1:
        return False, "", f"Year {dt.year} is outside plausible range"

    has_time = "%H" in expected_format
    normalized = dt.strftime("%Y-%m-%d %H:%M:%S") if has_time else dt.strftime("%Y-%m-%d")
    return True, normalized, ""


# --------------------------------------------------------------------------
# Numeric validation
# --------------------------------------------------------------------------

def validate_numeric(raw_value: Any, field_name: str,
                      allow_negative: bool = False,
                      allow_zero: bool = True) -> Tuple[bool, Optional[float], str]:
    if pd.isna(raw_value) or str(raw_value).strip() == "":
        return False, None, f"{field_name} is missing/empty"
    try:
        val = float(str(raw_value).replace(",", "").strip())
    except (ValueError, TypeError):
        return False, None, f"{field_name} is not numeric"
    if not allow_negative and val < 0:
        return False, val, f"{field_name} is negative"
    if not allow_zero and val == 0:
        return False, val, f"{field_name} is zero"
    return True, val, ""


# --------------------------------------------------------------------------
# Generic field checks
# --------------------------------------------------------------------------

def validate_required(raw_value: Any, field_name: str) -> Tuple[bool, str]:
    if pd.isna(raw_value) or str(raw_value).strip() == "":
        return False, f"{field_name} is required but missing"
    return True, ""


def normalize_categorical(raw_value: Any, allowed_values: Optional[List[str]] = None) -> Tuple[str, bool, str]:
    """Trims/title-cases a categorical value (e.g. payment_mode) and,
    if an allow-list is supplied, flags values outside it instead of
    silently accepting typos like 'cash ' or 'UPI '."""
    if pd.isna(raw_value):
        return "", False, "Value is missing"
    cleaned = str(raw_value).strip()
    normalized = cleaned.title() if cleaned.lower() not in {"upi", "cod"} else cleaned.upper()
    if allowed_values:
        allowed_norm = {a.lower() for a in allowed_values}
        if cleaned.lower() not in allowed_norm:
            return normalized, False, f"'{cleaned}' not in allowed set {allowed_values}"
    return normalized, True, ""

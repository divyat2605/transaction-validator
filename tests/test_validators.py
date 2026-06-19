import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from utils.validators import validate_phone, validate_date, validate_numeric, detect_date_format
from utils.processing import validate_dataframe, check_referential_integrity, split_into_chunks

RULES = {"IN": {"name": "India", "dial_code": "+91", "length": 10},
         "SG": {"name": "Singapore", "dial_code": "+65", "length": 8}}


def test_phone_valid_plain():
    ok, norm, reason = validate_phone("9876543210", "IN", RULES)
    assert ok and norm == "9876543210"


def test_phone_valid_with_dial_code_embedded():
    ok, norm, reason = validate_phone("919876543210", "IN", RULES)
    assert ok and norm == "9876543210"


def test_phone_wrong_length():
    ok, norm, reason = validate_phone("98765", "IN", RULES)
    assert not ok and "Expected 10" in reason


def test_phone_unknown_country():
    ok, norm, reason = validate_phone("12345678", "FR", RULES)
    assert not ok and "No phone rule" in reason


def test_phone_singapore_8_digits():
    ok, norm, reason = validate_phone("87654321", "sg", RULES)  # lower-case country code
    assert ok and norm == "87654321"


def test_date_iso_valid():
    ok, norm, reason = validate_date("2026-05-15", "%Y-%m-%d")
    assert ok and norm == "2026-05-15"


def test_date_wrong_format():
    ok, norm, reason = validate_date("15/05/2026", "%Y-%m-%d")
    assert not ok


def test_date_auto_detect():
    fmt = detect_date_format(["2026-05-15", "2026-06-01", "2026-06-10"])
    assert fmt == "%Y-%m-%d"


def test_numeric_negative_rejected():
    ok, val, reason = validate_numeric("-50", "amount", allow_negative=False)
    assert not ok


def test_numeric_valid():
    ok, val, reason = validate_numeric("199.99", "amount")
    assert ok and val == 199.99


def test_validate_dataframe_end_to_end():
    df = pd.DataFrame({
        "order_id": ["O1", "O2", "O2"],  # duplicate
        "phone": ["9876543210", "12", "87654321"],
        "country_code": ["IN", "IN", "SG"],
        "order_date": ["2026-05-01", "2026-05-02", "not-a-date"],
        "amount": [100, -5, 200],
    })
    clean, errors, summary = validate_dataframe(
        df, phone_col="phone", country_col="country_code", country_rules=RULES,
        date_cols=["order_date"], amount_cols=["amount"], id_col="order_id",
    )
    assert summary["total_rows"] == 3
    assert summary["invalid_rows"] >= 2
    assert len(clean) <= 1


def test_referential_integrity():
    parent = pd.DataFrame({"order_id": ["O1", "O2"]})
    child = pd.DataFrame({"order_id": ["O1", "O3"]})
    orphans = check_referential_integrity(child, "order_id", parent, "order_id")
    assert len(orphans) == 1
    assert orphans.iloc[0]["order_id"] == "O3"


def test_chunking():
    df = pd.DataFrame({"x": range(125)})
    chunks = split_into_chunks(df, max_rows=50)
    assert len(chunks) == 3
    assert sum(len(c) for c in chunks) == 125


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))

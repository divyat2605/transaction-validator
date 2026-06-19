"""
processing.py
--------------
Orchestrates validation across a whole dataframe (a single uploaded
file) and across files (referential integrity between orders / products
/ payments). Also handles splitting large outputs into chunks.

Kept independent of Streamlit so it can be unit tested / reused.
"""

from __future__ import annotations
import io
import math
import zipfile
import pandas as pd
from typing import Dict, List, Optional, Tuple

from .validators import (
    validate_phone, validate_date, validate_numeric, validate_required,
    normalize_categorical, detect_date_format,
)

# Column roles a file MAY declare. The UI lets the user map their actual
# column names onto these roles, so the engine isn't hard-coded to one
# exact schema (real client files rarely match a spec exactly).
ROLE_PHONE = "phone"
ROLE_COUNTRY = "country_code"
ROLE_DATE = "date"
ROLE_AMOUNT_LIST = "amount_fields"   # list of column names, validated as numeric >= 0
ROLE_QTY_LIST = "quantity_fields"
ROLE_REQUIRED_LIST = "required_fields"
ROLE_CATEGORICAL = "categorical_fields"  # dict: column -> allowed list (or None)
ROLE_ID = "id_field"                 # primary key for duplicate detection
ROLE_FK = "foreign_key_field"        # references another file's id_field


def validate_dataframe(
    df: pd.DataFrame,
    *,
    phone_col: Optional[str] = None,
    country_col: Optional[str] = None,
    country_rules: Optional[Dict] = None,
    date_cols: Optional[List[str]] = None,
    date_format_overrides: Optional[Dict[str, str]] = None,
    amount_cols: Optional[List[str]] = None,
    qty_cols: Optional[List[str]] = None,
    required_cols: Optional[List[str]] = None,
    categorical_cols: Optional[Dict[str, Optional[List[str]]]] = None,
    id_col: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """
    Runs all configured checks over `df`.

    Returns:
        clean_df   - rows with ALL checks passed, normalized values applied
        error_df   - original rows that failed >=1 check, with an
                     'validation_errors' column listing every reason
        summary    - dict of counts for the dashboard
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    n = len(df)
    errors_per_row: List[List[str]] = [[] for _ in range(n)]
    detected_formats: Dict[str, str] = {}

    # ---- required fields ----
    for col in (required_cols or []):
        if col not in df.columns:
            continue
        for i, v in enumerate(df[col]):
            ok, reason = validate_required(v, col)
            if not ok:
                errors_per_row[i].append(reason)

    # ---- duplicate primary key ----
    if id_col and id_col in df.columns:
        dup_mask = df[id_col].duplicated(keep=False) & df[id_col].notna()
        for i, is_dup in enumerate(dup_mask):
            if is_dup:
                errors_per_row[i].append(f"Duplicate {id_col}: {df.iloc[i][id_col]}")

    # ---- phone ----
    if phone_col and phone_col in df.columns and country_rules:
        cleaned_phones = [None] * n
        for i in range(n):
            raw_phone = df.iloc[i][phone_col]
            raw_country = df.iloc[i][country_col] if country_col and country_col in df.columns else ""
            ok, normalized, reason = validate_phone(raw_phone, raw_country, country_rules)
            cleaned_phones[i] = normalized
            if not ok:
                errors_per_row[i].append(f"{phone_col}: {reason}")
        df[phone_col] = cleaned_phones

    # ---- dates ----
    for col in (date_cols or []):
        if col not in df.columns:
            continue
        fmt = (date_format_overrides or {}).get(col) or detect_date_format(df[col].head(200).tolist())
        if fmt is None:
            for i in range(n):
                errors_per_row[i].append(f"{col}: could not auto-detect a consistent date format")
            continue
        detected_formats[col] = fmt
        normalized_vals = [None] * n
        for i in range(n):
            ok, normalized, reason = validate_date(df.iloc[i][col], fmt)
            normalized_vals[i] = normalized if ok else df.iloc[i][col]
            if not ok:
                errors_per_row[i].append(f"{col}: {reason}")
        df[col] = normalized_vals

    # ---- amounts / quantities (numeric, non-negative) ----
    for col in (amount_cols or []):
        if col not in df.columns:
            continue
        for i in range(n):
            ok, val, reason = validate_numeric(df.iloc[i][col], col, allow_negative=False)
            if ok:
                df.iat[i, df.columns.get_loc(col)] = val
            else:
                errors_per_row[i].append(reason)

    for col in (qty_cols or []):
        if col not in df.columns:
            continue
        for i in range(n):
            ok, val, reason = validate_numeric(df.iloc[i][col], col, allow_negative=False, allow_zero=False)
            if ok:
                df.iat[i, df.columns.get_loc(col)] = val
            else:
                errors_per_row[i].append(reason)

    # ---- categorical normalization ----
    for col, allowed in (categorical_cols or {}).items():
        if col not in df.columns:
            continue
        for i in range(n):
            normalized, ok, reason = normalize_categorical(df.iloc[i][col], allowed)
            df.iat[i, df.columns.get_loc(col)] = normalized
            if not ok:
                errors_per_row[i].append(f"{col}: {reason}")

    # ---- assemble outputs ----
    df["validation_errors"] = ["; ".join(e) if e else "" for e in errors_per_row]
    is_valid_mask = df["validation_errors"] == ""

    clean_df = df[is_valid_mask].drop(columns=["validation_errors"]).reset_index(drop=True)
    error_df = df[~is_valid_mask].reset_index(drop=True)

    summary = {
        "total_rows": n,
        "valid_rows": int(is_valid_mask.sum()),
        "invalid_rows": int((~is_valid_mask).sum()),
        "valid_pct": round(100 * is_valid_mask.sum() / n, 2) if n else 0,
        "detected_date_formats": detected_formats,
    }
    return clean_df, error_df, summary


def check_referential_integrity(
    child_df: pd.DataFrame, child_fk_col: str,
    parent_df: pd.DataFrame, parent_id_col: str,
) -> pd.DataFrame:
    """Flags rows in child_df whose foreign key has no matching row in
    parent_df (e.g. a product line referencing an order_id that doesn't
    exist in the orders file). Returns the orphaned rows only."""
    if child_fk_col not in child_df.columns or parent_id_col not in parent_df.columns:
        return pd.DataFrame()
    valid_ids = set(parent_df[parent_id_col].astype(str))
    orphan_mask = ~child_df[child_fk_col].astype(str).isin(valid_ids)
    return child_df[orphan_mask].copy()


def split_into_chunks(df: pd.DataFrame, max_rows: int = 50_000) -> List[pd.DataFrame]:
    """Splits a dataframe into a list of smaller dataframes, each capped
    at max_rows, so very large client files don't choke downstream
    systems or hit upload size limits."""
    if len(df) <= max_rows:
        return [df]
    n_chunks = math.ceil(len(df) / max_rows)
    return [df.iloc[i * max_rows: (i + 1) * max_rows].reset_index(drop=True) for i in range(n_chunks)]


def build_download_zip(file_groups: Dict[str, List[pd.DataFrame]]) -> bytes:
    """
    file_groups: { 'orders_clean': [df_chunk1, df_chunk2, ...], 'orders_errors': [df], ... }
    Returns zipped bytes containing one CSV per chunk, named
    '<group>_part1.csv', '<group>_part2.csv', etc.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for group_name, chunks in file_groups.items():
            for idx, chunk_df in enumerate(chunks, start=1):
                suffix = f"_part{idx}" if len(chunks) > 1 else ""
                csv_bytes = chunk_df.to_csv(index=False).encode("utf-8")
                zf.writestr(f"{group_name}{suffix}.csv", csv_bytes)
    buf.seek(0)
    return buf.read()

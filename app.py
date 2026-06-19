"""
Xeno Transaction Validation & Processing Platform
====================================================
A web platform that ingests order / product / payment transaction
files, validates them against configurable rules (country-specific
phone formats, date formats, numeric integrity, referential
integrity across files), and produces a cleaned, chunked, downloadable
output along with a full error report.

Run locally with:  streamlit run app.py
"""

import json
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from utils.processing import (
    validate_dataframe, check_referential_integrity,
    split_into_chunks, build_download_zip,
)

APP_DIR = Path(__file__).parent
CONFIG_PATH = APP_DIR / "config" / "country_rules.json"
SAMPLE_DIR = APP_DIR / "sample_data"

st.set_page_config(
    page_title="Transaction Validator",
    page_icon="https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/shield-check.svg", 
    layout="wide",
)

# --------------------------------------------------------------------------
# Session state init
# --------------------------------------------------------------------------
if "country_rules" not in st.session_state:
    with open(CONFIG_PATH) as f:
        st.session_state.country_rules = json.load(f)

if "raw_files" not in st.session_state:
    st.session_state.raw_files = {}      # name -> DataFrame
if "results" not in st.session_state:
    st.session_state.results = {}        # name -> (clean_df, error_df, summary)

FILE_TYPES = ["orders", "products", "payments"]
DEFAULT_REQUIRED = {
    "orders": ["order_id", "customer_name", "order_date", "total_amount"],
    "products": ["order_id", "product_id", "quantity", "unit_price"],
    "payments": ["payment_id", "order_id", "payment_mode", "amount"],
}


def read_uploaded(file) -> pd.DataFrame:
    if file.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(file)
    return pd.read_csv(file)


def guess_columns(df: pd.DataFrame) -> dict:
    """Best-effort auto-detection of column roles by name, so the user
    isn't forced to map every column by hand for a 'standard' file."""
    cols = list(df.columns)
    lower = {c: c.lower() for c in cols}

    def find(*keywords):
        for c in cols:
            if any(k in lower[c] for k in keywords):
                return c
        return None

    def find_all(*keywords):
        return [c for c in cols if any(k in lower[c] for k in keywords)]

    return {
        "id_col": find("order_id", "_id") if find("order_id") else find("id"),
        "phone_col": find("phone"),
        "country_col": find("country"),
        "date_cols": find_all("date", "datetime"),
        "amount_cols": find_all("amount", "price", "total"),
        "qty_cols": find_all("qty", "quantity"),
        "fk_col": find("order_id") if "order_id" in lower.values() else None,
    }


# --------------------------------------------------------------------------
# Sidebar — global configuration
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")

    st.subheader("Country phone rules")
    st.caption("Add/edit/remove countries — fully configurable, not hard-coded.")
    rules_df = pd.DataFrame([
        {"country_code": k, "name": v["name"], "dial_code": v["dial_code"], "digit_length": v["length"]}
        for k, v in st.session_state.country_rules.items()
    ])
    edited = st.data_editor(rules_df, num_rows="dynamic", use_container_width=True, key="rules_editor")
    if st.button("Apply rule changes", use_container_width=True):
        new_rules = {}
        for _, row in edited.iterrows():
            if pd.isna(row.get("country_code")) or str(row["country_code"]).strip() == "":
                continue
            new_rules[str(row["country_code"]).strip().upper()] = {
                "name": row.get("name", ""),
                "dial_code": str(row.get("dial_code", "")),
                "length": int(row["digit_length"]),
            }
        st.session_state.country_rules = new_rules
        st.success(f"Updated {len(new_rules)} country rules.")

    st.divider()
    st.subheader("Output chunking")
    chunk_size = st.number_input(
        "Max rows per output file", min_value=1000, max_value=500_000,
        value=50_000, step=1000,
        help="Large CSVs auto-split into multiple files of this many rows each.",
    )

    st.divider()
    if st.button("🔄 Reset everything", use_container_width=True):
        st.session_state.raw_files = {}
        st.session_state.results = {}
        st.rerun()

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title("Transaction Data Validation & Processing Platform")
st.write(
    "Upload order, product, and payment-mode transaction files. The platform "
    "validates phone numbers against country-specific rules, checks date "
    "formats, enforces data-integrity rules, and gives you back a cleaned, "
    "chunked, download-ready dataset plus a full error report."
)

tab_upload, tab_validate, tab_results, tab_about = st.tabs(
    ["1️⃣ Upload", "2️⃣ Validate", "3️⃣ Results & Download", "ℹ️ How it works"]
)

# --------------------------------------------------------------------------
# TAB 1 — Upload
# --------------------------------------------------------------------------
with tab_upload:
    st.subheader("Upload your files")
    use_sample = st.button("✨ Use sample data (for demo)")

    cols = st.columns(3)
    for i, ftype in enumerate(FILE_TYPES):
        with cols[i]:
            st.markdown(f"**{ftype.capitalize()}**")
            uploaded = st.file_uploader(
                f"{ftype}.csv / .xlsx", type=["csv", "xlsx", "xls"], key=f"uploader_{ftype}",
            )
            if uploaded is not None:
                st.session_state.raw_files[ftype] = read_uploaded(uploaded)
            if use_sample:
                st.session_state.raw_files[ftype] = pd.read_csv(SAMPLE_DIR / f"{ftype}.csv")
            if ftype in st.session_state.raw_files:
                df_preview = st.session_state.raw_files[ftype]
                st.caption(f"{len(df_preview):,} rows · {len(df_preview.columns)} columns")
                st.dataframe(df_preview.head(5), use_container_width=True, height=200)

    if use_sample:
        st.success("Loaded bundled sample data for Orders, Products, and Payments.")

# --------------------------------------------------------------------------
# TAB 2 — Configure & Validate
# --------------------------------------------------------------------------
with tab_validate:
    if not st.session_state.raw_files:
        st.info("Upload at least one file in the **Upload** tab first.")
    else:
        st.subheader("Map columns & run validation")
        st.caption("Auto-detected mappings are pre-filled — adjust anything that's wrong for your file.")

        configs = {}
        for ftype, df in st.session_state.raw_files.items():
            with st.expander(f"⚙️ {ftype.capitalize()} — column mapping", expanded=True):
                guess = guess_columns(df)
                cols_list = ["— none —"] + list(df.columns)

                c1, c2, c3 = st.columns(3)
                with c1:
                    id_col = st.selectbox(
                        "Primary ID column (for duplicate detection)", cols_list,
                        index=cols_list.index(guess["id_col"]) if guess["id_col"] in cols_list else 0,
                        key=f"id_{ftype}",
                    )
                    phone_col = st.selectbox(
                        "Phone number column", cols_list,
                        index=cols_list.index(guess["phone_col"]) if guess["phone_col"] in cols_list else 0,
                        key=f"phone_{ftype}",
                    )
                with c2:
                    country_col = st.selectbox(
                        "Country code column", cols_list,
                        index=cols_list.index(guess["country_col"]) if guess["country_col"] in cols_list else 0,
                        key=f"country_{ftype}",
                    )
                    date_cols = st.multiselect(
                        "Date / datetime columns", list(df.columns),
                        default=guess["date_cols"], key=f"dates_{ftype}",
                    )
                with c3:
                    amount_cols = st.multiselect(
                        "Amount / price columns (≥ 0)", list(df.columns),
                        default=guess["amount_cols"], key=f"amount_{ftype}",
                    )
                    qty_cols = st.multiselect(
                        "Quantity columns (> 0)", list(df.columns),
                        default=guess["qty_cols"], key=f"qty_{ftype}",
                    )

                required_cols = st.multiselect(
                    "Required (non-empty) columns", list(df.columns),
                    default=[c for c in DEFAULT_REQUIRED.get(ftype, []) if c in df.columns],
                    key=f"required_{ftype}",
                )

                fk_col = None
                if ftype != "orders" and "orders" in st.session_state.raw_files:
                    fk_col = st.selectbox(
                        "Foreign key → orders ID (referential check)", cols_list,
                        index=cols_list.index(guess["fk_col"]) if guess["fk_col"] in cols_list else 0,
                        key=f"fk_{ftype}",
                    )

                configs[ftype] = {
                    "id_col": None if id_col == "— none —" else id_col,
                    "phone_col": None if phone_col == "— none —" else phone_col,
                    "country_col": None if country_col == "— none —" else country_col,
                    "date_cols": date_cols,
                    "amount_cols": amount_cols,
                    "qty_cols": qty_cols,
                    "required_cols": required_cols,
                    "fk_col": None if fk_col in (None, "— none —") else fk_col,
                }

        st.divider()
        if st.button("🚀 Run validation", type="primary", use_container_width=True):
            results = {}
            with st.spinner("Validating..."):
                for ftype, df in st.session_state.raw_files.items():
                    cfg = configs[ftype]
                    clean_df, error_df, summary = validate_dataframe(
                        df,
                        phone_col=cfg["phone_col"],
                        country_col=cfg["country_col"],
                        country_rules=st.session_state.country_rules,
                        date_cols=cfg["date_cols"],
                        amount_cols=cfg["amount_cols"],
                        qty_cols=cfg["qty_cols"],
                        required_cols=cfg["required_cols"],
                        id_col=cfg["id_col"],
                    )

                    # Referential integrity vs orders, if applicable
                    if cfg["fk_col"] and "orders" in st.session_state.raw_files and ftype != "orders":
                        orders_id_col = configs["orders"]["id_col"]
                        if orders_id_col:
                            orphans = check_referential_integrity(
                                clean_df, cfg["fk_col"],
                                st.session_state.raw_files["orders"], orders_id_col,
                            )
                            if len(orphans):
                                orphans = orphans.copy()
                                orphans["validation_errors"] = (
                                    f"Orphan row: {cfg['fk_col']} not found in orders"
                                )
                                clean_df = clean_df[~clean_df.index.isin(orphans.index)]
                                error_df = pd.concat([error_df, orphans], ignore_index=True)
                                summary["invalid_rows"] += len(orphans)
                                summary["valid_rows"] -= len(orphans)
                                summary["valid_pct"] = round(
                                    100 * summary["valid_rows"] / summary["total_rows"], 2
                                ) if summary["total_rows"] else 0

                    results[ftype] = (clean_df, error_df, summary)
            st.session_state.results = results
            st.success("Validation complete — see the **Results & Download** tab.")

# --------------------------------------------------------------------------
# TAB 3 — Results & download
# --------------------------------------------------------------------------
with tab_results:
    if not st.session_state.results:
        st.info("Run validation in the **Validate** tab first.")
    else:
        zip_groups = {}
        for ftype, (clean_df, error_df, summary) in st.session_state.results.items():
            st.subheader(f"📦 {ftype.capitalize()}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total rows", f"{summary['total_rows']:,}")
            m2.metric("Valid rows", f"{summary['valid_rows']:,}")
            m3.metric("Invalid rows", f"{summary['invalid_rows']:,}")
            m4.metric("Valid %", f"{summary['valid_pct']}%")

            if summary.get("detected_date_formats"):
                st.caption(f"Auto-detected date formats: {summary['detected_date_formats']}")

            if len(error_df):
                with st.expander(f"⚠️ {len(error_df)} flagged rows — view details"):
                    # Quick breakdown of error reasons for the dashboard feel
                    reasons = (
                        error_df["validation_errors"].str.split("; ").explode().str.strip()
                    )
                    reasons = reasons[reasons != ""]
                    if len(reasons):
                        st.bar_chart(reasons.value_counts().head(10))
                    st.dataframe(error_df, use_container_width=True, height=250)

            with st.expander(f"✅ {len(clean_df)} cleaned rows — preview"):
                st.dataframe(clean_df.head(20), use_container_width=True)

            clean_chunks = split_into_chunks(clean_df, max_rows=chunk_size)
            if len(clean_chunks) > 1:
                st.caption(f"Cleaned output split into {len(clean_chunks)} chunked files "
                           f"({chunk_size:,} rows each).")
            zip_groups[f"{ftype}_clean"] = clean_chunks
            zip_groups[f"{ftype}_errors"] = [error_df] if len(error_df) else []
            st.divider()

        zip_groups = {k: v for k, v in zip_groups.items() if v}
        zip_bytes = build_download_zip(zip_groups)
        st.download_button(
            "⬇️ Download all results (ZIP)",
            data=zip_bytes,
            file_name="xeno_validated_transactions.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )

# --------------------------------------------------------------------------
# TAB 4 — About
# --------------------------------------------------------------------------
with tab_about:
    st.subheader("How this platform works")
    st.markdown(
        """
**Pipeline:** Upload → map columns to roles → validate → download.

**Validation rules applied**
- **Phone numbers** — cleaned (spaces/dashes/dial-codes stripped) and checked against a
  per-country expected digit length, fully configurable in the sidebar (no code changes
  needed to add a new country).
- **Dates** — the engine samples each date column, auto-detects the most likely format among
  common candidates (ISO, `dd/mm/yyyy`, `mm/dd/yyyy`, etc.), and flags values that don't match.
- **Amounts / quantities** — must be numeric and non-negative (quantities must be > 0).
- **Required fields** — flagged if blank.
- **Duplicate primary keys** — flagged within a file.
- **Referential integrity** — product/payment rows whose `order_id` has no matching row in
  Orders are flagged as orphans.

**Scalability**
- Validation runs vectorized where possible and degrades gracefully to per-row checks only
  where row-level error messages are needed.
- Output is automatically chunked into multiple files once it exceeds a configurable row
  threshold, so very large client exports stay manageable downstream.
- The validation engine (`utils/`) has no UI dependency, so it can be dropped behind a REST
  API or a background job queue without rewriting logic — only the Streamlit layer would
  need to change.

        """
    ) 

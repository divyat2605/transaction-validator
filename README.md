# Transaction Validation & Processing Platform

A web-based platform that ingests transaction data (orders, products, payment
modes), validates it against configurable rules, and returns a cleaned,
chunked, downloadable dataset plus a full error report.

Built for the Xeno Implementation Internship assignment — **Part 4: AI Empowerment**.

## Live demo

- **App:** `<paste your deployed Streamlit URL here>`
- **Walkthrough video (2 min):** `<paste your video link here>`

## What it does

1. **Upload** — accepts `orders`, `products`, and `payments` files (CSV or Excel).
2. **Map** — auto-detects which columns are phone numbers, dates, amounts,
   quantities, IDs, etc. (you can override any guess).
3. **Validate**
   - Phone numbers checked against **configurable, per-country digit-length
     rules** (e.g. India = 10 digits, Singapore = 8) — add a new country from
     the sidebar, no code change needed.
   - Dates auto-detected against common formats (ISO, `dd/mm/yyyy`,
     `mm/dd/yyyy`, …) and flagged if inconsistent.
   - Amounts/quantities checked for type and sign.
   - Required fields, duplicate IDs, and cross-file referential integrity
     (e.g. a product line whose `order_id` doesn't exist in Orders) are all
     flagged.
4. **Download** — a single ZIP containing the cleaned data (auto-split into
   chunks once it exceeds a configurable row count), the flagged-row error
   report, and on-screen summary metrics/charts.

## Architecture

```
app.py                 Streamlit UI — upload, column mapping, results, downloads
utils/validators.py    Pure validation functions (phone, date, numeric, categorical)
utils/processing.py    Orchestration: runs validators over a dataframe,
                        referential-integrity checks, chunking, ZIP building
config/country_rules.json   Default phone-rule config (editable at runtime in the UI)
sample_data/           Generated sample orders/products/payments with
                        intentionally injected errors, for demoing the tool
tests/test_validators.py    Unit tests for the validation engine
```

The validation engine (`utils/`) has **no Streamlit dependency** — it's plain
pandas/Python, so it's unit-testable in isolation and could sit behind a REST
API or a background worker without being rewritten.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Click **"Use bundled sample data"** in the Upload tab for an instant demo, or
upload your own files.

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Deploying

This app is a single Streamlit script with no database, so it deploys for
free on **Streamlit Community Cloud**:

1. Push this folder to a public (or private) GitHub repo.
2. Go to [share.streamlit.io](https://share.streamlit.io) → "New app" → point
   it at the repo, branch `main`, file `app.py`.
3. Deploy — you get a public `https://<name>.streamlit.app` URL.

(Render, Railway, or Fly.io also work if you'd rather containerize it — see
`requirements.txt` for the dependency list.)

## Design decisions & trade-offs

- **Streamlit over a custom React/FastAPI stack** — chosen for speed and
  reliability of free, public hosting within the assignment's timeline.
  Trade-off: less pixel-level UI control than a hand-built frontend.
- **Column-role mapping instead of a fixed schema** — real client CSVs rarely
  match a spec exactly (extra columns, renamed fields), so the user maps
  *roles* (which column is "phone", which is "amount") rather than the tool
  assuming exact column names.
- **In-memory, stateless processing** — no database; configuration lives in
  the session. Good enough for a single-user validation tool; would need a
  persistence layer for multi-user/team use.

## What was intentionally left out (and why)

- **Authentication / multi-tenant access** — out of scope for a single-purpose
  validation tool demoed by one person; would matter for a shared production
  deployment.
- **Distributed processing (Spark/Dask) for files larger than memory** — the
  current pandas-based approach comfortably handles the file sizes a CSV
  upload realistically involves; true big-data volumes would justify the
  added complexity.
- **Persistent, database-backed rule configuration** — country rules are
  editable in the running session; persisting them would need a small DB,
  which felt like premature infrastructure for an MVP.

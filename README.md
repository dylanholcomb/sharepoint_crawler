# SharePoint Reorganization Toolkit

End-to-end toolkit for SharePoint document discovery, AI-assisted reorganization
planning, and controlled move execution.

This repository includes:

- CLI workflow for crawl/analysis/proposal generation (`main.py`)
- Streamlit dashboard for human review + execution (`dashboard.py`, `pages/`)
- Optional Flask API backend (`src/api.py`) for remote orchestration

## What This Solves

- Inventories documents across all SharePoint document libraries
- Preserves stable source identifiers (`drive_id`, `item_id`) through planning
- Generates reorganization proposals (clean-slate + incremental)
- Lets admins approve/reject moves before execution
- Executes approved moves using item IDs (not ambiguous path guesses)

## Prerequisites

- Python 3.10+
- Azure AD app registration with Microsoft Graph permissions
  (see `AZURE_SETUP.md`)
- SharePoint Online site URL
- For Phase 2/3: Azure OpenAI deployment

## 1) Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in:

- `AZURE_TENANT_ID`
- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `SP_SITE_URL`
- `AZURE_OPENAI_KEY` and `AZURE_OPENAI_ENDPOINT` (for analyze/organize)

## 2) CLI End-to-End Flow

### Step A — Validate connection

```bash
python3 main.py --test
```

### Step B — Phase 2 analysis (crawl + extract + classify + flow advisory)

```bash
python3 main.py --analyze --output ./output
```

Key output:

- `sp_analysis_YYYYMMDD_HHMMSS.csv` (includes `drive_id`, `item_id`)

### Step C — Phase 3 proposal + migration CSVs

```bash
python3 main.py --organize --output ./output
```

Key outputs:

- `sp_proposal_YYYYMMDD_HHMMSS.json`
- `sp_migration_clean_YYYYMMDD_HHMMSS.csv`
- `sp_migration_incremental_YYYYMMDD_HHMMSS.csv`

Migration CSV rows include:

- `file_name`
- `drive_id` (source drive)
- `item_id` (source item ID)
- `current_path`
- `proposed_path`
- `reason`

## 3) Dashboard Flow (Human-in-the-loop)

Start dashboard:

```bash
streamlit run dashboard.py
```

Then:

1. Upload proposal JSON and migration CSV from `./output`
2. Review and approve/reject moves in **Review Moves**
3. Execute approved moves in **Execute**

For local dashboard execution, create `.streamlit/secrets.toml` with:

```toml
azure_tenant_id = "..."
azure_client_id = "..."
azure_client_secret = "..."
sp_site_url = "https://tenant.sharepoint.com/sites/YourSite"
admin_password = "" # optional
```

## 4) Optional Backend API

The Flask app in `src/api.py` provides:

- `GET /health`
- `POST /api/test-connection`
- `POST /api/organize`
- `POST /api/execute` (SSE progress)

Run locally:

```bash
python3 src/api.py
```

Optional env vars:

- `API_KEY` (for `X-API-Key` protection on `/api/*`)
- `ALLOWED_ORIGINS` (comma-separated CORS allowlist)

## Command Line Reference

```bash
python3 main.py [OPTIONS]

Options:
  --test            Test connection and permissions
  --analyze         Phase 2: crawl + extract + classify + flow discovery
  --organize        Phase 3: generate folder proposals + migration CSVs
  --csv PATH        Specific enriched CSV for --organize
  --output DIR      Output directory (default: ./output)
  --verbose, -v     Enable debug logging
```

## Project Structure

```text
main.py                    # CLI entry point (phases 1-3)
dashboard.py               # Streamlit dashboard entry
pages/                     # Review + execute dashboard pages
src/auth.py                # Graph auth client
src/crawler.py             # SharePoint crawler
src/extractor.py           # Text extraction
src/classifier.py          # AI classification
src/organizer.py           # Proposal generation
src/migration_executor.py  # ID-based move execution
src/api.py                 # Optional Flask API backend
```

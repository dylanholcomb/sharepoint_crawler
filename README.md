# SharePoint Document Crawler

A Python tool that crawls a SharePoint Online site, discovers all documents
across all document libraries, and exports a complete inventory with metadata.
Built for Mosaic Data Solutions' document reorganization initiative.

## What It Does

- Authenticates to SharePoint Online via Microsoft Graph API
- Recursively traverses all document libraries and folders
- Collects metadata for every file: name, type, size, dates, authors, paths
- Exports results as CSV (for spreadsheets), JSON (for programmatic use),
  and a visual folder structure map
- Identifies potential organizational issues (deeply nested files,
  overstuffed folders)

## Quick Start

### 1. Prerequisites

- PythonAnywhere account (Hacker tier or above — required for outbound
  HTTP to Microsoft Graph API)
- An Azure AD app registration with SharePoint permissions
  (see `AZURE_SETUP.md` for step-by-step instructions)

### 2. Deploy to PythonAnywhere

See `PYTHONANYWHERE_DEPLOY.md` for the full step-by-step guide. The short
version:

```bash
cd ~
git clone https://github.com/your-org/sp-crawler.git
cd sp-crawler
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # fill in your Azure AD + SharePoint details
```

### 3. Test Connection

```bash
python main.py --test
```

### 4. Run the Crawl

```bash
python main.py
```

Results will be saved to the `./output/` directory.

## Output Files

Each crawl produces three files (timestamped):

| File | Format | Purpose |
|------|--------|---------|
| `sp_crawl_YYYYMMDD_HHMMSS.csv` | CSV | Spreadsheet-friendly inventory of all documents |
| `sp_crawl_YYYYMMDD_HHMMSS.json` | JSON | Full data with summary statistics and analysis |
| `sp_structure_YYYYMMDD_HHMMSS.txt` | Text | Visual tree of the current folder structure |

### CSV Columns

- `file_name` — Document filename
- `extension` — File extension (.docx, .pdf, etc.)
- `size_bytes` / `size_readable` — File size
- `mime_type` — MIME type
- `library_name` — SharePoint document library name
- `folder_path` — Path within the library
- `full_path` — Complete path (library + folder + filename)
- `depth` — Folder nesting level (0 = library root)
- `created_date` / `modified_date` — Timestamps
- `created_by` / `modified_by` — Author names
- `web_url` — Direct link to the file in SharePoint

### JSON Summary

The JSON export includes an analysis summary with:

- File type distribution
- Total and average file sizes
- Folder depth analysis
- Author distribution
- Potential issues (overstuffed folders, deeply nested files)

## Command Line Options

```
python main.py [OPTIONS]

Options:
  --test            Test connection without crawling
  --output DIR      Output directory (default: ./output)
  --verbose, -v     Enable debug logging
```

## Project Structure

```
sp-crawler/
├── main.py                  # Entry point and CLI
├── src/
│   ├── __init__.py
│   ├── auth.py              # Microsoft Graph authentication
│   ├── crawler.py           # SharePoint recursive crawler
│   └── exporter.py          # CSV/JSON/structure export
├── requirements.txt         # Python dependencies
├── .env.example             # Configuration template
├── .gitignore
├── AZURE_SETUP.md           # Azure AD setup instructions
├── PYTHONANYWHERE_DEPLOY.md # PythonAnywhere deployment guide
└── README.md
```

## Next Steps

This crawler is Phase 1 (Discovery) of the document reorganization tool.
Upcoming phases:

- **Phase 2 — Content Analysis**: Extract text from documents, classify
  by topic using Azure OpenAI embeddings
- **Phase 3 — Recommendations**: Suggest improved folder structures based
  on document clustering and content similarity
- **Phase 4 — Dashboard**: Streamlit interface for visualizing current vs.
  proposed organization

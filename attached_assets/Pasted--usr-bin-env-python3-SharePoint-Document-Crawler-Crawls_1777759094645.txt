#!/usr/bin/env python3
"""
SharePoint Document Crawler
============================
Crawls a SharePoint Online site, discovers all documents, and exports
metadata to CSV/JSON for analysis and reorganization planning.

Usage:
    python main.py                    # Full crawl with default settings
    python main.py --test             # Test connection only
    python main.py --output ./results # Custom output directory
    python main.py --verbose          # Enable detailed logging

See AZURE_SETUP.md for authentication configuration.
"""

import argparse
import logging
import sys
import os
from pathlib import Path

# Ensure imports work regardless of where the script is invoked from
# (important for PythonAnywhere scheduled tasks which use absolute paths)
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from dotenv import load_dotenv

from src.auth import GraphAuthClient
from src.crawler import SharePointCrawler
from src.exporter import CrawlExporter
from src.extractor import DocumentExtractor
from src.classifier import DocumentClassifier
from src.flow_discovery import FlowDiscovery
from src.organizer import DocumentOrganizer


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config() -> dict:
    dotenv_path = PROJECT_DIR / ".env"
    load_dotenv(dotenv_path)

    required_vars = {
        "AZURE_TENANT_ID": os.getenv("AZURE_TENANT_ID"),
        "AZURE_CLIENT_ID": os.getenv("AZURE_CLIENT_ID"),
        "AZURE_CLIENT_SECRET": os.getenv("AZURE_CLIENT_SECRET"),
        "SP_SITE_URL": os.getenv("SP_SITE_URL"),
    }

    missing = [key for key, val in required_vars.items() if not val]

    if missing:
        print("ERROR: Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print("\nSee AZURE_SETUP.md for configuration instructions.")
        print("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    return required_vars


def test_connection(config: dict):
    logger = logging.getLogger(__name__)
    logger.info("Testing connection...")

    auth = GraphAuthClient(
        tenant_id=config["AZURE_TENANT_ID"],
        client_id=config["AZURE_CLIENT_ID"],
        client_secret=config["AZURE_CLIENT_SECRET"],
    )

    try:
        logger.info("Step 1: Acquiring access token...")
        auth.get_token()
        logger.info("  Token acquired successfully")

        logger.info("Step 2: Resolving SharePoint site...")
        site_info = auth.test_connection(config["SP_SITE_URL"])
        logger.info(f"  Site name: {site_info.get('displayName', 'N/A')}")
        logger.info(f"  Site ID:   {site_info.get('id', 'N/A')}")
        logger.info(f"  Web URL:   {site_info.get('webUrl', 'N/A')}")

        logger.info("Step 3: Listing document libraries...")
        site_id = site_info["id"]
        drives = auth.get_all_pages(f"/sites/{site_id}/drives")
        doc_libs = [d for d in drives if d.get("driveType") == "documentLibrary"]

        for lib in doc_libs:
            item_count = lib.get("quota", {}).get("used", "N/A")
            logger.info(f"  - {lib.get('name', 'Unnamed')}")

        logger.info("")
        logger.info("=" * 40)
        logger.info("CONNECTION TEST PASSED")
        logger.info(f"Found {len(doc_libs)} document libraries")
        logger.info("You're ready to run a full crawl.")
        logger.info("=" * 40)

    except Exception as e:
        logger.error("")
        logger.error("=" * 40)
        logger.error("CONNECTION TEST FAILED")
        logger.error(f"Error: {e}")
        logger.error("")
        logger.error("Common issues:")
        logger.error("  - Check your AZURE_TENANT_ID, CLIENT_ID, CLIENT_SECRET")
        logger.error("  - Verify API permissions are granted (admin consent)")
        logger.error("  - Confirm SP_SITE_URL is correct")
        logger.error("  - See AZURE_SETUP.md for troubleshooting")
        logger.error("=" * 40)
        sys.exit(1)


def run_crawl(config: dict, output_dir: str):
    logger = logging.getLogger(__name__)

    auth = GraphAuthClient(
        tenant_id=config["AZURE_TENANT_ID"],
        client_id=config["AZURE_CLIENT_ID"],
        client_secret=config["AZURE_CLIENT_SECRET"],
    )

    crawler = SharePointCrawler(auth, config["SP_SITE_URL"])
    documents = crawler.crawl()

    if not documents:
        logger.warning("No documents found. The site may be empty.")
        return

    exporter = CrawlExporter(
        documents=documents,
        stats=crawler.stats,
        output_dir=output_dir,
    )

    csv_path = exporter.export_csv()
    json_path = exporter.export_json()
    structure_path = exporter.export_structure_map()

    logger.info("")
    logger.info("OUTPUT FILES:")
    logger.info(f"  CSV (spreadsheet):   {csv_path}")
    logger.info(f"  JSON (full data):    {json_path}")
    logger.info(f"  Structure map:       {structure_path}")


def run_analysis(config: dict, output_dir: str):
    logger = logging.getLogger(__name__)

    aoai_key = os.getenv("AZURE_OPENAI_KEY")
    aoai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    aoai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    if not aoai_key or not aoai_endpoint:
        print("ERROR: Phase 2 requires Azure OpenAI configuration.")
        print("Add these to your .env file:")
        print("  AZURE_OPENAI_KEY=your-key")
        print("  AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/")
        print("  AZURE_OPENAI_DEPLOYMENT=gpt-4o  (optional, defaults to gpt-4o)")
        sys.exit(1)

    auth = GraphAuthClient(
        tenant_id=config["AZURE_TENANT_ID"],
        client_id=config["AZURE_CLIENT_ID"],
        client_secret=config["AZURE_CLIENT_SECRET"],
    )

    logger.info("=" * 60)
    logger.info("PHASE 2: CONTENT ANALYSIS")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Step 1/4: Crawling SharePoint site...")
    crawler = SharePointCrawler(auth, config["SP_SITE_URL"])
    documents = crawler.crawl()

    if not documents:
        logger.warning("No documents found. The site may be empty.")
        return

    logger.info("")
    logger.info("Step 2/4: Extracting document content...")
    extractor = DocumentExtractor(auth)

    libraries = crawler._get_document_libraries()
    primary_drive_id = libraries[0]["id"] if libraries else ""

    for i, doc in enumerate(documents):
        if i % 20 == 0:
            logger.info(f"  Extracting: {i}/{len(documents)} documents")

        drive_item_path = doc.get("drive_item_path", "")
        drive_id = primary_drive_id

        if "/drives/" in drive_item_path:
            try:
                parts = drive_item_path.split("/drives/")[1].split("/")
                drive_id = parts[0]
            except (IndexError, KeyError):
                pass

        text = extractor.extract_text(
            drive_item_id=doc["item_id"],
            drive_id=drive_id,
            file_name=doc["file_name"],
            extension=doc["extension"],
        )
        doc["extracted_text"] = text

    extracted_count = sum(1 for d in documents if d.get("extracted_text"))
    logger.info(f"  Text extracted from {extracted_count}/{len(documents)} documents")

    logger.info("")
    logger.info("Step 3/4: Classifying documents with AI...")
    classifier = DocumentClassifier(
        api_key=aoai_key,
        endpoint=aoai_endpoint,
        deployment=aoai_deployment,
    )
    documents = classifier.classify_batch(documents)

    logger.info("")
    logger.info("Step 4/4: Discovering Power Automate flows...")
    flow_discovery = FlowDiscovery(auth, crawler.site_id)
    flow_discovery.discover_site_workflows()
    flow_report = flow_discovery.generate_flow_report()

    logger.info("")
    logger.info("Exporting results...")

    for doc in documents:
        doc.pop("extracted_text", None)

    exporter = CrawlExporter(
        documents=documents,
        stats=crawler.stats,
        output_dir=output_dir,
    )

    enriched_csv = exporter.export_enriched_csv()
    json_path = exporter.export_json()
    structure_path = exporter.export_structure_map()
    flow_path = exporter.export_flow_report(flow_report)

    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 2 COMPLETE")
    logger.info("=" * 60)
    logger.info("OUTPUT FILES:")
    logger.info(f"  Enriched CSV:        {enriched_csv}")
    logger.info(f"  JSON (full data):    {json_path}")
    logger.info(f"  Structure map:       {structure_path}")
    logger.info(f"  Flow report:         {flow_path}")
    logger.info("")
    logger.info("NEXT STEPS:")
    logger.info("  1. Review the enriched CSV for AI classifications")
    logger.info("  2. Share the flow report with site admin / flow owners")
    logger.info("  3. Run --organize with the enriched CSV to get folder proposals")


def run_organize(config: dict, output_dir: str, csv_path: str):
    logger = logging.getLogger(__name__)

    aoai_key = os.getenv("AZURE_OPENAI_KEY")
    aoai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    aoai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    if not aoai_key or not aoai_endpoint:
        print("ERROR: --organize requires Azure OpenAI configuration in .env")
        sys.exit(1)

    if not csv_path:
        output_path = Path(output_dir)
        csvs = sorted(output_path.glob("sp_analysis_*.csv"), reverse=True)
        if not csvs:
            print(f"ERROR: No enriched CSV found in {output_dir}")
            print("Run --analyze first to generate the classified document inventory.")
            sys.exit(1)
        csv_path = str(csvs[0])
        logger.info(f"Using most recent enriched CSV: {csv_path}")

    logger.info("=" * 60)
    logger.info("PHASE 3: FOLDER STRUCTURE PROPOSALS")
    logger.info("=" * 60)

    organizer = DocumentOrganizer(
        api_key=aoai_key,
        endpoint=aoai_endpoint,
        deployment=aoai_deployment,
    )

    proposal = organizer.organize(csv_path)
    files = organizer.export_proposal(proposal, output_dir)

    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 3 COMPLETE")
    logger.info("=" * 60)
    logger.info("OUTPUT FILES:")
    logger.info(f"  Proposal JSON:             {files['proposal_json']}")
    logger.info(f"  Clean Slate Migration CSV: {files['clean_slate_csv']}")
    logger.info(f"  Incremental Migration CSV: {files['incremental_csv']}")
    logger.info("")
    logger.info("Review the migration CSVs to see proposed moves.")
    logger.info("Each row shows: file, current location, proposed location, reason.")


def main():
    parser = argparse.ArgumentParser(
        description="Crawl a SharePoint Online site and inventory all documents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --test              Test connection and permissions
  python main.py                     Run full crawl, output to ./output/
  python main.py --analyze           Phase 2: crawl + extract + classify + flows
  python main.py --organize          Phase 3: propose folder structures from analysis
  python main.py --organize --csv path/to/sp_analysis.csv  Use specific CSV
  python main.py --output ./results  Custom output directory
  python main.py --verbose           Enable detailed debug logging
        """,
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Test connection and permissions without crawling",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Phase 2: crawl, extract content, classify with AI, discover flows",
    )
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Phase 3: propose folder structures from enriched CSV",
    )
    parser.add_argument(
        "--csv",
        default="",
        help="Path to enriched CSV for --organize (auto-detects most recent if omitted)",
    )
    parser.add_argument(
        "--output",
        default="./output",
        help="Output directory for results (default: ./output)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    config = load_config()

    if args.test:
        test_connection(config)
    elif args.analyze:
        run_analysis(config, args.output)
    elif args.organize:
        run_organize(config, args.output, args.csv)
    else:
        run_crawl(config, args.output)


if __name__ == "__main__":
    main()

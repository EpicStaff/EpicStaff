import json
import logging
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, create_model

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__file__)

# ------------------------------------------------------------------
# Load args schema
# ------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).parent / "args_schema.json"

with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    args_schema_data = json.load(f)

# ------------------------------------------------------------------
# Dynamic Pydantic model (Pydantic v2 compatible)
# ------------------------------------------------------------------


def create_args_model(schema: dict) -> type[BaseModel]:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    model_fields = {}

    for name, meta in properties.items():
        json_type = meta.get("type")
        default = meta.get("default", ... if name in required else None)

        if json_type == "string":
            py_type = str
        elif json_type == "integer":
            py_type = int
        elif json_type == "boolean":
            py_type = bool
        else:
            py_type = Any

        model_fields[name] = (
            py_type,
            Field(default, description=meta.get("description", "")),
        )

    return create_model(schema.get("title", "ArgsModel"), **model_fields)


ArgsModel = create_args_model(args_schema_data)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

BASE_API_URL = "http://export.arxiv.org/api/query"
ATOM_NAMESPACE = "{http://www.w3.org/2005/Atom}"
SUMMARY_TRUNCATE_LENGTH = 300
REQUEST_TIMEOUT = 10
SLEEP_DURATION = 1

# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------


def get_element_text(entry: ET.Element, element_name: str) -> Optional[str]:
    elem = entry.find(f"{ATOM_NAMESPACE}{element_name}")
    return elem.text.strip() if elem is not None and elem.text else None


def extract_pdf_url(entry: ET.Element) -> Optional[str]:
    for link in entry.findall(ATOM_NAMESPACE + "link"):
        if link.attrib.get("title", "").lower() == "pdf":
            return link.attrib.get("href")
    for link in entry.findall(ATOM_NAMESPACE + "link"):
        href = link.attrib.get("href")
        if href and "pdf" in href:
            return href
    return None


def validate_save_path(path: str) -> Path:
    save_path = Path(path).resolve()
    save_path.mkdir(parents=True, exist_ok=True)
    return save_path


def download_pdf(pdf_url: str, save_path: Path) -> None:
    logger.info(f"Downloading PDF from {pdf_url} → {save_path}")
    urllib.request.urlretrieve(pdf_url, str(save_path))
    logger.info(f"Saved: {save_path}")


# ------------------------------------------------------------------
# Core logic
# ------------------------------------------------------------------


def fetch_arxiv_data(search_query: str, max_results: int) -> List[Dict[str, Any]]:
    api_url = (
        f"{BASE_API_URL}"
        f"?search_query={urllib.parse.quote(search_query)}"
        f"&start=0&max_results={max_results}"
    )

    logger.info(f"Fetching Arxiv data: {api_url}")

    with urllib.request.urlopen(api_url, timeout=REQUEST_TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {response.reason}")
        xml_data = response.read().decode("utf-8")

    root = ET.fromstring(xml_data)
    papers = []

    for entry in root.findall(ATOM_NAMESPACE + "entry"):
        raw_id = get_element_text(entry, "id")
        arxiv_id = raw_id.split("/")[-1].replace(".", "_") if raw_id else "unknown"

        title = get_element_text(entry, "title") or "No Title"
        summary = get_element_text(entry, "summary") or "No Summary"
        published = get_element_text(entry, "published") or "No Publish Date"

        authors = [
            get_element_text(author, "name") or "Unknown"
            for author in entry.findall(ATOM_NAMESPACE + "author")
        ]

        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "summary": summary,
                "authors": authors,
                "published_date": published,
                "pdf_url": extract_pdf_url(entry),
            }
        )

    return papers


def format_paper(paper: Dict[str, Any]) -> str:
    summary = (
        paper["summary"][:SUMMARY_TRUNCATE_LENGTH] + "..."
        if len(paper["summary"]) > SUMMARY_TRUNCATE_LENGTH
        else paper["summary"]
    )

    return (
        f"Title: {paper['title']}\n"
        f"Authors: {', '.join(paper['authors'])}\n"
        f"Published: {paper['published_date']}\n"
        f"PDF: {paper['pdf_url'] or 'N/A'}\n"
        f"Summary: {summary}"
    )


# ------------------------------------------------------------------
# Tool entrypoint
# ------------------------------------------------------------------


def main(**kwargs) -> str:
    """
    Arxiv Paper Tool entrypoint.
    Fully schema-driven.
    """
    try:
        args = ArgsModel(**kwargs)

        papers = fetch_arxiv_data(
            search_query=args.search_query, max_results=args.max_results
        )

        if getattr(args, "download_pdfs", False):
            save_dir = validate_save_path(getattr(args, "save_dir", "./arxiv_pdfs"))

            for paper in papers:
                if paper["pdf_url"]:
                    filename_base = (
                        re.sub(r'[\\/*?:"<>|]', "_", paper["title"]).strip()
                        if getattr(args, "use_title_as_filename", False)
                        else paper["arxiv_id"]
                    )
                    filename = f"{filename_base[:500]}.pdf"
                    download_pdf(paper["pdf_url"], save_dir / filename)
                    time.sleep(SLEEP_DURATION)
        return "\n\n" + "-" * 80 + "\n\n".join(format_paper(p) for p in papers)
    except ValidationError as e:
        return f"Invalid arguments:\n{e}"

    except Exception as e:
        logger.exception("Arxiv tool failed")
        return f"Error: {e}"

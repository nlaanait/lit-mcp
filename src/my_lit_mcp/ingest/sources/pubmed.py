from __future__ import annotations

import time
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from my_lit_mcp.ingest import PaperRecord, normalize_doi


def search_pubmed(
    query: str,
    *,
    api_key: str = "",
    max_results: int = 25,
    sleep_seconds: float = 0.35,
) -> list[PaperRecord]:
    params: dict[str, Any] = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key
    with httpx.Client(timeout=60.0) as client:
        esearch = client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params
        )
        esearch.raise_for_status()
        time.sleep(sleep_seconds)
        ids = esearch.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        fetch_params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "xml",
        }
        if api_key:
            fetch_params["api_key"] = api_key
        efetch = client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params=fetch_params,
        )
        efetch.raise_for_status()
        time.sleep(sleep_seconds)
        return _parse_pubmed_xml(efetch.text)


def _parse_pubmed_xml(xml_text: str) -> list[PaperRecord]:
    root = ET.fromstring(xml_text)
    papers: list[PaperRecord] = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find("MedlineCitation")
        if medline is None:
            continue
        pmid = medline.findtext("PMID")
        art = medline.find("Article")
        if art is None:
            continue
        title = (art.findtext("ArticleTitle") or "").strip()
        abstract_parts = [
            (n.text or "").strip()
            for n in art.findall("./Abstract/AbstractText")
            if (n.text or "").strip()
        ]
        authors = []
        for author in art.findall("./AuthorList/Author"):
            last = author.findtext("LastName") or ""
            fore = author.findtext("ForeName") or ""
            name = f"{fore} {last}".strip()
            if name:
                authors.append(name)
        year = None
        published_at = None
        date_node = art.find("./Journal/JournalIssue/PubDate")
        if date_node is not None:
            y = date_node.findtext("Year")
            if y and y.isdigit():
                year = int(y)
                month = date_node.findtext("Month") or "01"
                day = date_node.findtext("Day") or "01"
                published_at = f"{y}-{month}-{day}"
        doi = None
        for id_node in article.findall(".//ArticleId"):
            if id_node.attrib.get("IdType") == "doi" and id_node.text:
                doi = normalize_doi(id_node.text)
        venue = art.findtext("./Journal/Title")
        papers.append(
            PaperRecord(
                title=title,
                abstract="\n".join(abstract_parts) or None,
                authors=", ".join(authors) or None,
                year=year,
                published_at=published_at,
                venue=venue,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                source="pubmed",
                doi=doi,
                pmid=pmid,
            )
        )
    return papers

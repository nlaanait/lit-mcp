from __future__ import annotations

import time
from xml.etree import ElementTree as ET

import httpx

from my_lit_mcp.ingest import PaperRecord, normalize_doi


def search_arxiv(
    query: str, *, max_results: int = 25, sleep_seconds: float = 3.0
) -> list[PaperRecord]:
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.get("https://export.arxiv.org/api/query", params=params)
        resp.raise_for_status()
        time.sleep(sleep_seconds)
        return _parse_atom(resp.text)


def _parse_atom(xml_text: str) -> list[PaperRecord]:
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_text)
    papers: list[PaperRecord] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        published = entry.findtext("atom:published", default="", namespaces=ns) or None
        authors = [
            (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for a in entry.findall("atom:author", ns)
        ]
        arxiv_id = None
        id_text = entry.findtext("atom:id", default="", namespaces=ns) or ""
        if "arxiv.org/abs/" in id_text:
            arxiv_id = id_text.rsplit("/abs/", 1)[-1]
        doi = None
        doi_el = entry.find("arxiv:doi", ns)
        if doi_el is not None and doi_el.text:
            doi = normalize_doi(doi_el.text)
        pdf_url = None
        abs_url = None
        for link in entry.findall("atom:link", ns):
            href = link.attrib.get("href")
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = href
            if link.attrib.get("rel") == "alternate":
                abs_url = href
        if arxiv_id and not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        year = int(published[:4]) if published and len(published) >= 4 else None
        papers.append(
            PaperRecord(
                title=title.replace("\n", " "),
                abstract=abstract,
                authors=", ".join(a for a in authors if a) or None,
                year=year,
                published_at=published,
                venue="arXiv",
                url=abs_url or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None),
                source="arxiv",
                doi=doi,
                arxiv_id=arxiv_id,
                oa_pdf_url=pdf_url,
            )
        )
    return papers

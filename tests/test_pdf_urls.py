from __future__ import annotations

from my_lit_mcp.pdf.urls import iter_pdf_urls, normalize_pdf_url


def test_biorxiv_doi_org_url_normalizes_to_full_pdf():
    url = "https://doi.org/10.64898/2026.08.07.742341"
    doi = "10.64898/2026.08.07.742341"
    assert normalize_pdf_url(url, doi=doi, venue="bioRxiv") == (
        "https://www.biorxiv.org/content/10.64898/2026.08.07.742341v2.full.pdf"
    )


def test_biorxiv_content_page_gets_full_pdf_suffix():
    url = "https://www.biorxiv.org/content/10.64898/2026.08.07.742341v2"
    assert normalize_pdf_url(url) == (
        "https://www.biorxiv.org/content/10.64898/2026.08.07.742341v2.full.pdf"
    )


def test_arxiv_doi_normalizes_to_pdf():
    doi = "10.48550/arxiv.2409.13669"
    assert normalize_pdf_url("https://doi.org/" + doi, doi=doi) == (
        "https://arxiv.org/pdf/2409.13669.pdf"
    )


def test_existing_pdf_url_is_unchanged():
    url = "https://arxiv.org/pdf/2409.13669.pdf"
    assert normalize_pdf_url(url) == url


def test_iter_pdf_urls_tries_biorxiv_versions():
    doi = "10.64898/2026.08.07.742341"
    urls = list(
        iter_pdf_urls(
            "https://doi.org/" + doi,
            doi=doi,
            venue="bioRxiv",
        )
    )
    assert urls[0].endswith("v2.full.pdf")
    assert any(u.endswith("v1.full.pdf") for u in urls)

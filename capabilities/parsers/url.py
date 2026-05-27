"""URL scraper via trafilatura. Fetches + extracts main content."""
from __future__ import annotations


def parse(url: str) -> str:
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise RuntimeError(f"failed to fetch {url}")
    extracted = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    return extracted or ""

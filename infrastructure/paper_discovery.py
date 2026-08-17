from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field


class PaperCandidate(BaseModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    landing_url: str | None = None
    pdf_url: str | None = None
    is_open_access: bool = False


class PaperDiscovery(Protocol):
    def search(self, query: str, limit: int = 5) -> list[PaperCandidate]: ...

    def resolve(self, identifier: str) -> PaperCandidate: ...


class OpenAlexPaperDiscovery:
    """Metadata and legal open-access locations from the public OpenAlex API."""

    api_root = "https://api.openalex.org"

    def __init__(self, *, timeout_seconds: float = 15) -> None:
        self._timeout = timeout_seconds

    def search(self, query: str, limit: int = 5) -> list[PaperCandidate]:
        query = query.strip()
        if not query:
            raise ValueError("paper search query cannot be empty")
        limit = max(1, min(limit, 10))
        payload = self._get("/works", params={"search": query, "per-page": limit})
        return [_candidate(item) for item in payload.get("results", [])]

    def resolve(self, identifier: str) -> PaperCandidate:
        value = identifier.strip()
        doi = extract_doi(value)
        if doi:
            payload = self._get(f"/works/https://doi.org/{quote(doi, safe='/()')}")
            return _candidate(payload)
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.path.casefold().endswith(".pdf"):
            return PaperCandidate(title=parsed.path.rsplit("/", 1)[-1], pdf_url=value)
        raise ValueError("provide a DOI, doi.org URL, or direct HTTPS PDF URL")

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        with httpx.Client(
            timeout=self._timeout,
            trust_env=False,
            headers={"User-Agent": "ChemResearch-Agent/0.1 (mailto:contact@example.invalid)"},
        ) as client:
            response = client.get(f"{self.api_root}{path}", params=params)
            if response.status_code == 404:
                raise ValueError("paper was not found")
            response.raise_for_status()
            return response.json()


def extract_doi(value: str) -> str | None:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", value, flags=re.IGNORECASE)
    return match.group(0).rstrip(".,;)") if match else None


def looks_like_paper_identifier(value: str) -> bool:
    stripped = value.strip()
    return bool(extract_doi(stripped)) or (
        stripped.startswith("https://") and stripped.casefold().split("?", 1)[0].endswith(".pdf")
    )


def _candidate(item: dict) -> PaperCandidate:
    best = item.get("best_oa_location") or {}
    primary = item.get("primary_location") or {}
    pdf_url = best.get("pdf_url") or primary.get("pdf_url")
    if pdf_url and not str(pdf_url).startswith("https://"):
        pdf_url = None
    doi = item.get("doi")
    if doi:
        doi = str(doi).removeprefix("https://doi.org/")
    return PaperCandidate(
        title=item.get("display_name") or item.get("title") or "Untitled paper",
        authors=[
            authorship.get("author", {}).get("display_name")
            for authorship in item.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        ][:12],
        year=item.get("publication_year"),
        doi=doi,
        landing_url=best.get("landing_page_url") or primary.get("landing_page_url"),
        pdf_url=pdf_url,
        is_open_access=bool((item.get("open_access") or {}).get("is_oa")),
    )

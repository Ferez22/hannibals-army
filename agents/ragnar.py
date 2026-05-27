"""RAGNAR — ingestion chief. Detects format, routes to parser, returns RawDocument."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.base_agent import AgentResult, BaseAgent
from capabilities.parsers import EXT_FORMATS, EXT_PARSERS, parse_url
from core.entity_types import RawDocument

log = logging.getLogger("hannibal.ragnar")


class Ragnar(BaseAgent):
    name = "RAGNAR"
    tagline = "ingestion chief — parses any document"
    persona = (
        "You are RAGNAR, ingestion chief. You raid documents and bring their content back. "
        "You parse pdf, docx, pptx, xlsx, images, and urls into RawDocuments."
    )

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        """task: {"source": str}  where source is file path or URL."""
        source = task.get("source")
        if not source:
            return AgentResult(False, error="missing 'source' in task")

        try:
            if _is_url(source):
                return self._parse_url(source)
            return self._parse_file(Path(source))
        except Exception as e:
            log.exception("ragnar_failed", extra={"source": source})
            return AgentResult(False, error=f"{type(e).__name__}: {e}")

    def _parse_file(self, path: Path) -> AgentResult:
        if not path.exists():
            return AgentResult(False, error=f"file not found: {path}")

        ext = path.suffix.lower()
        if ext not in EXT_PARSERS:
            return AgentResult(False, error=f"unsupported format: {ext}")

        log.info("ragnar_parse_start", extra={"path": str(path), "format": ext})
        text = EXT_PARSERS[ext](path)
        doc = RawDocument(
            source=str(path),
            format=EXT_FORMATS[ext],
            raw_text=text,
            metadata={
                "filename": path.name,
                "size_bytes": path.stat().st_size,
            },
            extracted_at=datetime.now(),
        )
        log.info(
            "ragnar_parse_done",
            extra={"path": str(path), "chars": len(text)},
        )
        return AgentResult(True, data=doc)

    def _parse_url(self, url_str: str) -> AgentResult:
        log.info("ragnar_url_start", extra={"url": url_str})
        text = parse_url(url_str)
        if not text:
            return AgentResult(False, error=f"empty content from {url_str}")
        doc = RawDocument(
            source=url_str,
            format="url",
            raw_text=text,
            metadata={"url": url_str},
            extracted_at=datetime.now(),
        )
        log.info("ragnar_url_done", extra={"url": url_str, "chars": len(text)})
        return AgentResult(True, data=doc)


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


RAGNAR = Ragnar()


# ---------------------------------------------------------------------------
# CLI smoke test:  python -m agents.ragnar <path-or-url>
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    from rich.logging import RichHandler

    logging.basicConfig(level=logging.INFO, handlers=[RichHandler(markup=True)], force=True)

    if len(sys.argv) < 2:
        print("usage: python -m agents.ragnar <path-or-url>")
        sys.exit(1)

    result = RAGNAR.invoke({"source": sys.argv[1]})
    if not result.success:
        print(f"FAILED: {result.error}")
        sys.exit(1)

    doc: RawDocument = result.data
    print(f"\nsource:   {doc.source}")
    print(f"format:   {doc.format}")
    print(f"chars:    {len(doc.raw_text)}")
    print(f"metadata: {doc.metadata}")
    print(f"\n--- preview (first 500 chars) ---")
    print(doc.raw_text[:500])

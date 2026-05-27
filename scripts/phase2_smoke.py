"""Phase 2 end-to-end smoke test.

Ingest 3 docs, ask ORACLE a question, print result.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Allow running from repo root: `python scripts/phase2_smoke.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.logging import RichHandler

logging.basicConfig(level=logging.INFO, handlers=[RichHandler(markup=True, show_path=False)], force=True)

from agents.oracle import ORACLE
from core.ingestion_pipeline import get_kg, ingest

console = Console()

SAMPLES = [
    Path("data/samples/Handbook (1).docx"),
    Path("data/samples/MITRA (1).xlsx"),
    Path("data/samples/Procuration_sonia-hassas.pdf"),
]

QUESTIONS = [
    "Who is the CEO of Qartmina?",
    "Who participated in the power of attorney signing?",
    "What projects exist?",
]


def main() -> int:
    kg = get_kg()

    console.rule("[#5BC8F5]INGESTION[/]")
    for sample in SAMPLES:
        if not sample.exists():
            console.print(f"[red]skip {sample} (missing)[/]")
            continue
        console.print(f"\n[#F5A623]→ {sample.name}[/]")
        result = ingest(str(sample))
        if not result.success:
            console.print(f"  [red]FAIL: {result.error}[/]")
            continue
        data = result.data
        console.print(f"  [#2ECC71]promoted:[/] {data['extraction_summary']['promoted']}")
        console.print(f"  [#F5D020]staged:[/] {data['extraction_summary']['staged']}")
        console.print(f"  [dim]corroborated: {data['extraction_summary']['corroborated']}  edges: {data['extraction_summary']['edges_added']}[/]")

    console.rule("[#5BC8F5]GRAPH STATE[/]")
    for et in ["Person", "Team", "Project", "Rule", "Event", "Document"]:
        nodes = kg.list_live(et)
        console.print(f"  {et:10s} live: {len(nodes)}")
    console.print(f"  [dim]pending staging: {kg.pending_count()}[/]")

    console.rule("[#5BC8F5]ORACLE QUERIES[/]")
    for q in QUESTIONS:
        console.print(f"\n[#F5A623]Q:[/] {q}")
        result = ORACLE.invoke({"question": q})
        if not result.success:
            console.print(f"  [red]FAIL: {result.error}[/]")
            continue
        console.print(f"[#2ECC71]A:[/] {result.data}")
        console.print(f"[dim]cited: {len(result.cited_nodes)} nodes[/]")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Hannibal's Army — agents.

Uses lazy imports so that running `python -m agents.<agent>` does not
double-load the agent module (avoids RuntimeWarning from runpy).
"""
from __future__ import annotations


def all_agents() -> list:
    """Return all agent singletons. Imported lazily."""
    from agents.cartographer import CARTOGRAPHER
    from agents.donna import DONNA
    from agents.hannibal import HANNIBAL
    from agents.oracle import ORACLE
    from agents.ragnar import RAGNAR

    return [HANNIBAL, RAGNAR, CARTOGRAPHER, ORACLE, DONNA]


__all__ = ["all_agents"]

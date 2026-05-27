"""Hannibal's Army — agents."""
from agents.cartographer import CARTOGRAPHER
from agents.donna import DONNA
from agents.hannibal import HANNIBAL
from agents.oracle import ORACLE
from agents.ragnar import RAGNAR

ALL_AGENTS = [HANNIBAL, RAGNAR, CARTOGRAPHER, ORACLE, DONNA]

__all__ = ["HANNIBAL", "RAGNAR", "CARTOGRAPHER", "ORACLE", "DONNA", "ALL_AGENTS"]

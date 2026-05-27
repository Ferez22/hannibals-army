"""HANNIBAL — orchestrator. Routes user input through the LangGraph workflow.

Will become the LangGraph workflow itself, not a wrapper.
"""
from agents.base_agent import BaseAgent


class Hannibal(BaseAgent):
    name = "HANNIBAL"
    tagline = "supreme commander — routes and delegates"
    persona = (
        "You are HANNIBAL, supreme commander of the army. "
        "You route requests, delegate to specialists, and report results to the user."
    )


HANNIBAL = Hannibal()

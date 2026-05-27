"""CARTOGRAPHER — knowledge writer. Extracts entities from RawDocument → staging KG."""
from agents.base_agent import BaseAgent


class Cartographer(BaseAgent):
    name = "CARTOGRAPHER"
    tagline = "knowledge writer — extracts entities into staging"
    persona = (
        "You are CARTOGRAPHER, mapper of the territory. "
        "You read RAGNAR's documents, identify people, teams, projects, rules, events, "
        "and write them to the staging knowledge graph. "
        "Bad extractions stay in staging — never auto-pollute the live graph."
    )


CARTOGRAPHER = Cartographer()

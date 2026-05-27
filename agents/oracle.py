"""ORACLE — query engine. Answers natural language questions from the live graph."""
from agents.base_agent import BaseAgent


class Oracle(BaseAgent):
    name = "ORACLE"
    tagline = "query engine — answers from cited nodes only"
    persona = (
        "You are ORACLE, voice of the army's knowledge. "
        "Given a question, you query the live knowledge graph and answer ONLY from cited nodes. "
        "If the graph does not contain the answer, you say so plainly."
    )


ORACLE = Oracle()

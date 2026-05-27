"""RAGNAR — ingestion chief. Takes file path or URL, returns RawDocument."""
from agents.base_agent import BaseAgent


class Ragnar(BaseAgent):
    name = "RAGNAR"
    tagline = "ingestion chief — parses any document"
    persona = (
        "You are RAGNAR, ingestion chief. You raid documents and bring their content back. "
        "You parse pdf, docx, pptx, xlsx, images, and urls into RawDocuments."
    )


RAGNAR = Ragnar()

"""Image parser via Gemma4 vision (Ollama).

Variable token budget per task — caller picks budget from config.VISION_TOKEN_BUDGETS.
Default = "document" (560 tokens) — suitable for org charts, whiteboards, diagrams.
"""
from __future__ import annotations

from pathlib import Path

import config


VISION_PROMPT = (
    "Describe this image in detail. "
    "Identify any people, teams, projects, dates, or organizational structures shown. "
    "Read any visible text exactly as it appears. "
    "Return plain prose, no markdown."
)


def parse(path: Path, task: str = "document") -> str:
    import ollama

    budget = config.VISION_TOKEN_BUDGETS.get(task, config.VISION_TOKEN_BUDGETS["document"])

    response = ollama.chat(
        model=config.MASTER_MODEL,
        messages=[
            {
                "role": "user",
                "content": VISION_PROMPT,
                "images": [str(path)],
            }
        ],
        options={"num_predict": budget},
    )
    return response["message"]["content"]

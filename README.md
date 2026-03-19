# Getting started

This project uses `uv` for dependency management.

## Options

### 1. TUI Trip Planner (Recommended)

Interactive terminal-based trip planning with intelligent country matching and budget filtering.

```bash
uv run simple_tui_planner.py
```

Features:

- 🌍 Smart country matching based on budget and trip type
- 📝 Interactive TUI with step-by-step workflow
- 🎯 Personalized trip recommendations
- 💾 Export to JSON (PDF, Markdown, YAML coming soon)
- 📊 Scoring algorithm for optimal destinations

### 2. Chat-based Trip Planner

AI-powered trip planning with MCP (Model Context Protocol) integration.

```bash
uv run main.py
```

Note in main.py, the model loaded is an Ollama model, make sure you have it running locally.
Otherwise you can chose to run with a different model by changing the `llm` variable in `main.py`:

```python
# 1. Select Chat Model:
# either:
llm = init_chat_model(<model>)
# or:
llm = OllamaLLM(model=<model_name>)
```

## Configure the digital twin

Copy the `digital-twin-config.sample.yml` file to `digital-twin-config.yml` and fill in your personal information.

Please note that you can extend this file with your own custom configuration sections. You can also shape it as you wish. Of course, the more information you put the better.

## To Do's

### Next To Do's:

- Modify trip organizer to include some of the extracted suggestions in the plan
- Edit internet search to filter based on season and budget
- streamlit:
  - chat interface
  - extracted suggestions as widgets
  - Load more suggestions
- Save a trip:

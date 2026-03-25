# Getting started

This project uses `uv` for dependency management. Recommended is to install **Ollama** and run it with a **model of choice** then go to `main.py` and adjust the model name. You can also use an LLM of choice.

## Data (Kaggle → local CSV → sorted CSV)

### 1) Download / load the dataset from Kaggle

Run from the project root:

```bash
uv run db/load_destinations.py
```

Notes:
- The loader uses `kagglehub`.
- Make sure the dataset id and `file_path` inside `db/load_destinations.py` match the dataset you want to use.
- The rest of the project expects the raw CSV at `data/tourist_destinations.csv`.

### 2) Sort the dataset + add a `Description` column

This script sorts by `Country` (then `Destination Name`), adds an empty `Description` column, and writes a new CSV:

```bash
uv run utils/clean_trip_destinations_data.py
```

Output:
- `data/tourist_destinations_sorted.csv`

## Options

Either run the Terminal UI, or run the chatbot in the terminal. The TUI doesn't include the websearch (Tavily) yet ! If you want the websearch next to the AI extracted suggestions, then please head to tavily and get yourself an API key. Then copy the `.env.sample` file to `.env` and add your `TAVILY_API_KEY`


### 1. TUI Trip Planner (Recommended)

Interactive terminal-based trip planning with intelligent country matching and budget filtering.

```bash
uv run simple_tui_planner.py
```

Features:

- **No web search yet !**
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

# Getting started

### Start the project

This project uses `uv` for dependency management.
Start with `uv run main.py`.

Note in main.py, the model loaded is an Ollama model, make sure you have it running locally.
Otherwise you can chose to run with a different model by changing the `llm` variable in `main.py`:

```python
# 1. Select Chat Model:
# either:
llm = init_chat_model(<model>)
# or:
llm = OllamaLLM(model=<model_name>)
```

### Configure the digital twin

Copy the `digital-twin-config.sample.yml` file to `digital-twin-config.yml` and fill in your personal information.

Please note that you can extend this file with your own custom configuration sections. You can also shape it as you wish. Of course, the more information you put the better.

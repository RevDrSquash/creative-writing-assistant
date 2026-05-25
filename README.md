# Writing Agent v2

A local-first AI writing workspace for long-form fiction and worldbuilding. It brings prose, Story Bible data, and AI collaboration into one app so writers can keep continuity without juggling disconnected chat transcripts.

The AI is wired into the workspace through a LangGraph agent and a tool layer, so it can read and edit project content directly instead of just generating text for manual copy/paste.

See [`docs/overview.md`](docs/overview.md) and [`docs/architecture.md`](docs/architecture.md) for the full picture, and [`docs/implementation_plan.md`](docs/implementation_plan.md) for current progress.

## Tech stack

- **Python** with **Poetry** for dependency management
- **NiceGUI** for the three-column UI (navigation, editor, chat)
- **LangGraph** + **LangChain** for the agent loop and tool calls
- **OpenRouter**-compatible models (via `langchain-openai`)
- **Pydantic** for data modeling

## Prerequisites

- Python `^3.10`
- [Poetry](https://python-poetry.org/docs/#installation) `>=2.0`
- An [OpenRouter API key](https://openrouter.ai/keys)

## Setup

1. Clone the repo and `cd` into it.

2. Install dependencies. Poetry is configured to create the virtualenv inside the project (`.venv/`):

   ```bash
   poetry install
   ```

3. Create a `.env` file from the template and fill in your key:

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` and set `OPENROUTER_API_KEY` (must start with `sk-or-v1-`).

## Run

Launch the NiceGUI app:

```bash
poetry run writing-agent
```

Or equivalently:

```bash
poetry run python -m app.ui.app
```

NiceGUI will print a local URL (typically <http://localhost:8080>); open it in a browser.

## Tests

```bash
poetry run pytest
```

## Lint

```bash
poetry run ruff check .
```

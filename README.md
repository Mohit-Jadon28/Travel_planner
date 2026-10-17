# AI Travel Planner

A multi-agent travel-planning application built with LangGraph, LangChain, Groq, and Tavily. It combines specialist agents for flights, hotels, food, attractions, transport, and budget planning, then runs optimization, critique, and guardrail stages before producing a travel plan.

The project includes both a Streamlit interface and a command-line runner. Generated plans can be exported as PDF, and the run report records agent execution and resource usage.

## Features

- Parallel specialist agents coordinated by a LangGraph workflow
- Budget-aware itinerary planning with bounded optimization and critique loops
- Groq-powered language model calls and Tavily web search
- Request and output guardrails, a jailed file sandbox, and bounded per-agent resources
- Optional reference-file grounding and persistent token-saving memory
- Streamlit UI and CLI, with PDF and JSON report output

## Requirements

- Python 3.11 or newer
- A Groq API key
- A Tavily API key

## Setup

From the repository root, create and activate a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the application dependencies and prepare local configuration:

```powershell
Set-Location .\travel_planner
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `travel_planner/.env` and set `GROQ_API_KEY` and `TAVILY_API_KEY`. Never commit `.env` or paste API keys into source files. The checked-in `.env.example` is only a template.

## Run the application

Start the web application from the `travel_planner` directory:

```powershell
streamlit run streamlit_app.py
```

Run the command-line example:

```powershell
python main.py
```

The CLI accepts a JSON request, optional reference files, an output directory, and run controls:

```powershell
python main.py --config .\request.json --reference-file .\trip_reference.md --out-dir .\outputs
```

The planner writes a PDF itinerary and a JSON execution report to the selected output directory. These runtime artifacts and persistent agent memory are intentionally excluded from Git.

## Project layout

```text
.
├── graph.py
├── README.md
└── travel_planner/
    ├── main.py                 # CLI entry point
    ├── planner_service.py      # Shared application service
    ├── streamlit_app.py        # Web UI
    ├── requirements.txt
    └── travel_planner/
        ├── agents.py           # Specialist agents and workflow nodes
        ├── graph.py            # LangGraph workflow
        ├── guardrails.py       # Input and output checks
        ├── schemas.py          # Typed request and workflow state
        ├── tools.py            # Search and sandbox tools
        └── ...
```

## Configuration

The application reads settings from environment variables or a local `.env` file:

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Required Groq API credential |
| `TAVILY_API_KEY` | Required Tavily search credential |
| `GROQ_MODEL` | Groq model name; defaults to `openai/gpt-oss-120b` |
| `GROQ_TEMPERATURE` | Model temperature |
| `GROQ_MAX_TOKENS` | Maximum completion tokens |
| `TRAVEL_MAX_LLM_CALLS` | Maximum LLM calls allowed for a run |
| `TRAVEL_SANDBOX_DIR` | Optional sandbox directory override |
| `TRAVEL_MEMORY_PATH` | Optional persistent memory file override |

See `travel_planner/.env.example` for the complete local configuration template.

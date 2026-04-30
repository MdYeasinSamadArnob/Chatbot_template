# AI Orchestration Chatbot

A production-level AI chatbot that mimics Metabase's Metabot orchestration pattern.
Backend: FastAPI + LiteLLM + CrewAI (memory) + Ollama.
Frontend: Next.js 14 App Router + Zustand + Tailwind CSS.

---

## Prerequisites

- [Python 3.11+](https://www.python.org/downloads/) (via `py` launcher on Windows)
- [Node.js 18+](https://nodejs.org/)
- [Ollama](https://ollama.com/download) installed and running

---

## 1. Pull the Ollama model

```bash
ollama pull llama3.2
```

---

## 2. Backends (Split)

From the repository root (`Chatbot_template`), run this once:

```bash
# Create one shared virtualenv for both backend services
python3 -m venv .venv

# Install backend dependencies once
.venv/bin/pip install -r bot-socket/requirements.txt
```

Then start both backends in separate terminals:

```bash
# Terminal 1
cd /home/arnob/Chatbot_template/bot-socket
../.venv/bin/python -m app.main
```

```bash
# Terminal 2
cd /home/arnob/Chatbot_template/admin-api
../.venv/bin/python -m app.main
```

Notes:
- Both services read port from their `.env` files.
- Expected ports: bot-socket `9001`, admin-api `9002`.
- Do not run `source .env`; values are loaded by Pydantic settings.

API docs available at:
- bot-socket: http://localhost:9001/docs
- admin-api: http://localhost:9002/docs

---

## 3. Frontends

Open a second terminal:

```bash
cd /home/arnob/Chatbot_template/bot-ui

# Install dependencies (first time only)
npm install

# Copy environment config (first time only)
cp .env.local.example .env.local

# Start bot-ui (port 3001)
npm run dev
```

Open http://localhost:3001 — the chat sidebar opens by default.

For the admin editor app:

```bash
cd /home/arnob/Chatbot_template/admin-ui
npm install
npm run dev
```

Open http://localhost:3002.

---

## 4. Run with Docker Compose

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cd /home/arnob/Chatbot_template
docker compose up --build
```

| Service    | URL                        |
|------------|----------------------------|
| Bot UI     | http://localhost:3001      |
| Bot Socket | http://localhost:9001/docs |
| Admin API  | http://localhost:9002/docs |
| Ollama     | http://localhost:11434     |

> On first run, pull the model inside the Ollama container:
> ```bash
> docker exec -it demo_project-ollama-1 ollama pull llama3.2
> ```

---

## 5. Adding a new tool

1. Create `bot-socket/app/tools/my_tool.py`:

```python
from pydantic import BaseModel
from app.tools.base import register_tool

class MyInput(BaseModel):
    value: str

@register_tool("my_tool", "Does something useful", MyInput)
async def my_tool(value: str) -> str:
    return f"Result: {value}"
```

2. Register it in `bot-socket/app/tools/__init__.py`:

```python
from app.tools import my_tool
```

3. That's it — the tool is automatically available to all agent profiles.

---

## Project structure

```
Chatbot_template/
├── bot-socket/
│   ├── app/
│   │   ├── agent/          # core.py (orchestration loop), memory, profiles, prompts, streaming
│   │   ├── api/            # Chat + socket FastAPI routers
│   │   ├── tools/          # calculator, datetime, web_search + registry
│   │   ├── config.py
│   │   └── main.py
│   ├── requirements.txt
│   └── .env.example
├── admin-api/
│   ├── app/
│   │   ├── api/            # KB admin FastAPI routers
│   │   ├── db/
│   │   ├── tools/
│   │   └── main.py
│   ├── requirements.txt
│   └── .env.example
├── bot-ui/
│   ├── src/
│   │   ├── app/            # Next.js App Router pages + API proxy routes
│   │   ├── components/     # ChatSidebar, ChatContainer, message components
│   │   ├── hooks/          # useChat
│   │   ├── lib/            # streaming (AI SDK v4 line protocol parser)
│   │   └── store/          # Zustand chatStore + types
│   └── .env.local.example
├── admin-ui/
│   ├── src/
│   │   ├── app/            # Next.js App Router + admin proxy routes
│   │   ├── components/     # EditorPane, PreviewPane, HistorySidebar
│   │   └── lib/
│   └── package.json
└── docker-compose.yml
```

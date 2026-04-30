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

## 2. Backend

# Stop backend server by port
fuser -k 9001/tcp

# OR stop by process name/pattern
pkill -f "uvicorn app.main:app --reload --port 9001"

```powershell
cd Demo_Project\backend

# Create virtual environment (first time only)
py -m venv .venv

# Activate
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate          # macOS / Linux

# Install dependencies (first time only)
pip install -r requirements.txt

# Copy environment config (first time only)
Copy-Item .env.example .env          # Windows
# cp .env.example .env               # macOS / Linux

# Start the backend (port 8000)
uvicorn app.main:app --reload --port 9001
```
uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload

API docs available at http://localhost:8000/docs

---

## 3. Frontend

Open a second terminal:

```powershell
cd Demo_Project\frontend

# Install dependencies (first time only)
npm install

# Copy environment config (first time only)
Copy-Item .env.local.example .env.local    # Windows
# cp .env.local.example .env.local         # macOS / Linux

# Start the frontend (port 3000)
npm run dev
```

Open http://localhost:3000 — the chat sidebar opens by default.

---

## 4. Run with Docker Compose

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cd Demo_Project
docker compose up --build
```

| Service  | URL                        |
|----------|----------------------------|
| Frontend | http://localhost:3000       |
| Backend  | http://localhost:8000/docs  |
| Ollama   | http://localhost:11434      |

> On first run, pull the model inside the Ollama container:
> ```bash
> docker exec -it demo_project-ollama-1 ollama pull llama3.2
> ```

---

## 5. Adding a new tool

1. Create `backend/app/tools/my_tool.py`:

```python
from pydantic import BaseModel
from app.tools.base import register_tool

class MyInput(BaseModel):
    value: str

@register_tool("my_tool", "Does something useful", MyInput)
async def my_tool(value: str) -> str:
    return f"Result: {value}"
```

2. Register it in `backend/app/tools/__init__.py`:

```python
from app.tools import my_tool
```

3. That's it — the tool is automatically available to all agent profiles.

---

## Project structure

```
Demo_Project/
├── backend/
│   ├── app/
│   │   ├── agent/          # core.py (orchestration loop), memory, profiles, prompts, streaming
│   │   ├── api/            # FastAPI routers
│   │   ├── tools/          # calculator, datetime, web_search + registry
│   │   ├── config.py
│   │   └── main.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router pages + API proxy routes
│   │   ├── components/     # ChatSidebar, ChatContainer, message components
│   │   ├── hooks/          # useChat
│   │   ├── lib/            # streaming (AI SDK v4 line protocol parser)
│   │   └── store/          # Zustand chatStore + types
│   └── .env.local.example
└── docker-compose.yml
```

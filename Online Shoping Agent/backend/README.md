# AI Shopping Assistant — Backend

A production-ready FastAPI + LangGraph backend for an AI-powered shopping assistant.

## Stack
- **FastAPI** — async HTTP framework
- **LangGraph** — stateful agent pipeline
- **MongoDB (Motor)** — async database + TTL cache
- **JWT** — authentication
- **eBay Finding API** — product search (mock fallback included)
- **OpenAI GPT-4o-mini** — query understanding, disambiguation, intent routing, response generation

---

## Quickstart

```bash
cd backend

# 1. Create virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env and fill in your keys
cp .env.example .env
# Edit .env — set MONGODB_URI, OPENAI_API_KEY, etc.

# 4. Run
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

---

## Architecture

```
POST /api/v1/search
        │
        ▼
  JWT Auth + Rate Limit
        │
        ▼
  LangGraph Pipeline
  ┌─────────────────────────────────────────────────────┐
  │  query_understanding → disambiguation                │
  │        │                   │                        │
  │    [clear]            [ambiguous] → ask question    │
  │        │                                            │
  │   intent_router                                     │
  │     /      \                                        │
  │  search    chat                                     │
  │    │          └──► tool_loop (max 3 iter)           │
  │    ▼                product_detail / search_tool    │
  │  validation → cache_lookup → decision_engine        │
  │                   reuse  │  partial/new             │
  │                    │     └──► api_call              │
  │                    └──────────────────┐             │
  │                               filtering             │
  │                               diversity             │
  │                               ranking               │
  │                               formatter             │
  └─────────────────────────────────────────────────────┘
        │
        ▼
  Checkpointer → save state to MongoDB
        │
        ▼
  Return SearchResponse
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `MONGODB_URI` | MongoDB connection string |
| `MONGODB_DB_NAME` | Database name (default: `shopping_agent`) |
| `JWT_SECRET_KEY` | Secret for signing JWTs |
| `OPENAI_API_KEY` | OpenAI API key (optional — mock fallback used if absent) |
| `OPENAI_MODEL` | Model name (default: `gpt-4o-mini`) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `EBAY_APP_ID` | eBay Finding API app ID (optional — mock fallback used) |
| `RATE_LIMIT_PER_MINUTE` | Search rate limit (default: 20) |
| `CACHE_TTL_SECONDS` | Product cache TTL (default: 3600) |

---

## API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/signup` | Register new user |
| POST | `/api/v1/auth/login` | Email/password login |
| POST | `/api/v1/auth/google` | Google OAuth login |
| GET | `/api/v1/auth/me` | Get current user profile |
| PUT | `/api/v1/auth/update` | Update name/phone |
| POST | `/api/v1/auth/address` | Add address |
| PUT | `/api/v1/auth/address/{id}` | Update address |
| DELETE | `/api/v1/auth/address/{id}` | Delete address |
| PUT | `/api/v1/auth/address/{id}/default` | Set default address |

### Threads
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/threads` | List all threads (sidebar) |
| GET | `/api/v1/threads/{id}` | Load chat history |
| PUT | `/api/v1/threads/{id}` | Rename thread |
| DELETE | `/api/v1/threads/{id}` | Soft-delete thread |

### Search
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/search` | Main query endpoint |

### Feedback
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/feedback` | Record click/like/ignore |

---

## Running Tests

```bash
pytest
```

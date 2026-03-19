# AgentQueue

Self-hosted AI task manager that runs Claude Code (and other LLMs) on your machine while you're away — so your tokens don't expire unused.

**Kanban board + smart idle detection + token budget management + live output streaming.**

---

## How it works

AgentQueue watches your X11 idle time. When you step away, it automatically launches queued tasks in tmux sessions. When you come back, you can jump straight into the running session. Everything stays on your machine — no central server, no SaaS, no data leaves your network.

```
[ BACKLOG      ]  [ SCHEDULED    ]  [ IN PROGRESS  ]  [ DONE         ]
[ Write tests  ]  [ Refactor DB  ]  [* Add auth *  ]  [ Docs v1.2    ]
[ Blog post    ]  [ in ~20min    ]  [ ||||||||     ]  [ 2h ago       ]
[ [evergreen]  ]  [              ]  [ [jump in]    ]  [              ]
```

Token budget bar always visible at the top. Drag tasks between columns. Click "Jump in" to attach to the tmux session mid-run.

---

## Quick start

```bash
git clone <repo>
cd agentqueue

cp .env.example .env        # edit at minimum SECRET_KEY
make install                # creates venv + installs deps
make migrate                # applies all migrations
python manage.py setup_agentqueue   # interactive onboarding
make dev                    # starts daphne + celery worker + celery beat
```

Then open `http://localhost:8000`.

### Requirements

- Python 3.11+
- Redis (for Celery + Channels)
- tmux
- `xprintidle` for X11 idle detection (`sudo apt install xprintidle`)
- Claude CLI (`claude`) if using Claude Max provider

---

## Makefile targets

| Command | What it does |
|---|---|
| `make install` | Create venv and install all dependencies |
| `make dev` | Start daphne + celery worker + celery beat |
| `make migrate` | Run database migrations |
| `make worker` | Start Celery worker only |
| `make beat` | Start Celery beat only |
| `make test` | Run pytest suite |
| `make lint` | Run ruff + black check |

---

## LLM Providers

| Provider | How it works |
|---|---|
| **Claude Max** | Calls `claude --print` CLI subprocess — uses your existing Claude Max subscription |
| **Anthropic API** | Official `anthropic` SDK with your API key |
| **OpenRouter** | 100+ models via OpenAI-compatible API (`openai` SDK, custom `base_url`) |
| **Ollama** | Local models via `httpx` streaming to `localhost:11434` |

Configure providers in the admin or via `setup_agentqueue`. Multiple configs supported — assign different providers to different projects or tasks.

---

## Task types

- **One-shot**: runs once, moves to Done on completion
- **Evergreen**: recurring tasks with a cron expression — automatically rescheduled after each run
- **Chained**: ordered sequence of tasks that run one after another

---

## Smart scheduler

The scheduler runs every 60 seconds via Celery beat and applies this decision tree:

1. Any tasks in backlog/scheduled?
2. Within allowed hours + days?
3. Token budget not exhausted?
4. No task currently in progress?
5. Is the machine idle? (xprintidle >= threshold OR last activity > away_threshold hours ago)
6. Token spreading: are we ahead of the weekly budget curve?

If all checks pass, it picks the highest-priority task and launches it.

**Drain mode**: if your Claude session expires within `drain_threshold_hours`, spreading is bypassed and tasks run aggressively to use remaining budget. End-of-week drain kicks in if >85% of the week has passed but <70% of budget was used.

---

## tmux integration

Each task runs in a named tmux window: `agentqueue:task-{id}`. The "Jump in" button on a task card copies the attach command to your clipboard:

```bash
tmux attach -t agentqueue:task-42
```

You can take over, edit files, run follow-up commands — AgentQueue keeps streaming output to the dashboard regardless.

---

## AI task suggestions

Open a project, click "Suggest Tasks". AgentQueue reads your repo's README and recent git log, sends it to your configured LLM, and returns a list of concrete tasks to add. Review and approve each one individually.

---

## Token budget

Set a weekly limit per provider. AgentQueue tracks tokens used per run and accumulates them against the weekly budget. Configurable budget curve controls spending rate across the week (e.g. spend at most 20% of budget in the first 25% of the week).

---

## Architecture

```
Browser <-- WebSocket --> DashboardConsumer <-- Redis channel layer <-- Celery tasks
                                                                         (output chunks,
                                                                          status updates)
```

- Django 5.1 + Django Channels 4.3 for WebSocket
- Celery 5.4 + Redis for task queue and periodic scheduling
- HTMX 2 + Alpine.js 3 + SortableJS for frontend (no build step)
- TailwindCSS via CDN
- SQLite by default (set `DATABASE_URL` for Postgres)

---

## Configuration

All settings via `.env`:

```bash
SECRET_KEY=your-secret-key-here
DEBUG=True
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=                        # leave empty for SQLite
ALLOWED_HOSTS=localhost,127.0.0.1
```

Scheduling, token budgets, and provider configs are managed via the web UI or Django admin.

---

## Running tests

```bash
make test
# or
.venv/bin/pytest tests/ -v
```

19 tests covering models, providers, and the scheduling engine.

---

## Future: OpenClaw integration

Once the REST API is stable, a companion OpenClaw skill will be published to ClawdHub. This will let you query task status, trigger tasks, and get reports via natural language — from any device where OpenClaw is running. No changes needed in AgentQueue itself: the skill just calls the local API.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

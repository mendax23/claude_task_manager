# AgentQueue

**Queue AI tasks. Walk away. Come back to results.**

Localhost Kanban board that auto-launches tasks in tmux when your machine goes idle — so your Claude Max tokens don't expire unused while your screen is locked.

```
[ BACKLOG       ]  [ SCHEDULED    ]  [ IN PROGRESS  ]  [ DONE         ]
[ Write tests   ]  [ Refactor DB  ]  [▶ Add auth   ]  [ Docs v1.2    ]
[ Blog post     ]  [ in ~20 min   ]  [ ████████░░   ]  [ 2h ago       ]
[ [evergreen]   ]  [              ]  [ [jump in]    ]  [              ]
                                       ↑ tmux session, streaming live
```

---

## What it does

- **Idle detection** — polls `xprintidle`, launches tasks when you step away
- **Token budgets** — weekly limits per provider with configurable spending curves
- **Live output** — streams tmux pane output to the board via WebSocket
- **Jump in** — one click copies `tmux attach -t agentqueue:task-42` to clipboard
- **Evergreen tasks** — cron-scheduled, auto-reschedule after each run
- **Task chains** — ordered sequences that trigger step by step
- **AI suggestions** — reads your repo README + git log, proposes concrete tasks

---

## Install

**Needs:** Python 3.11+, Redis, tmux, [`xprintidle`](https://github.com/mph009/xprintidle)

```bash
git clone <repo> && cd agentqueue
python -m venv .venv
cp .env.example .env      # set SECRET_KEY at minimum
make install              # pip install into .venv
make migrate              # create SQLite database
make setup                # interactive onboarding
```

Then open **3 terminals:**

```bash
make dev      # web server  →  http://localhost:3333
make worker   # Celery task runner
make beat     # Celery scheduler (checks for tasks every 60s)
```

---

## Providers

| Provider | What you need |
|---|---|
| **Claude Max** | `claude` CLI installed and logged in |
| **Anthropic API** | `ANTHROPIC_API_KEY` in `.env` |
| **OpenRouter** | `OPENROUTER_API_KEY` in `.env` |
| **Ollama** | Running at `localhost:11434` |

Multiple configs supported — assign different providers per project.

---

## Stack

Django 5.1 · Channels · Celery + Redis · HTMX 2 · Alpine.js · SortableJS · SQLite (Postgres-ready)

No build step. No npm. Everything via CDN.

---

## License

[Apache 2.0](LICENSE)

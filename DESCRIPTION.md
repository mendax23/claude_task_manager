# AgentQueue — Projektbeschreibung

## Kurzfassung

AgentQueue ist ein selbstgehostetes Kanban-Board, das KI-Aufgaben automatisch startet, wenn der Rechner im Leerlauf ist. Ziel: ungenutzte Claude-Max-Tokens produktiv einsetzen, ohne aktiv am Bildschirm zu sitzen. Tasks werden in tmux-Sessions ausgeführt und lassen sich live im Browser verfolgen oder per Terminal betreten.

---

## Problemstellung

Claude Max bietet ein wöchentliches Token-Kontingent. Wer nicht durchgehend am Rechner arbeitet, verschwendet Kapazität. Gleichzeitig gibt es immer Aufgaben — Tests schreiben, Code refactoren, Dokumentation erstellen —, die ein LLM autonom erledigen kann. AgentQueue schließt diese Lücke: Aufgaben in die Queue legen, Bildschirm sperren, zurückkommen zu Ergebnissen.

---

## Architektur

```
Browser (HTMX + Alpine.js)
    │
    ├── HTTP ──→ Django Views (Tasks, Projects, Scheduling, Providers)
    │
    └── WebSocket ──→ Django Channels (Live-Output, Status-Updates)
                          │
                          ▼
                    Redis (Channel Layer + Celery Broker)
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
         Celery Beat   Celery Worker  SQLite
         (Scheduler)   (Task Runner)  (Datenbank)
              │           │
              │           ├──→ tmux (Prozess-Isolation)
              │           └──→ LLM Provider (Claude CLI / API / OpenRouter / Ollama)
              │
              └──→ xprintidle (Leerlauferkennung)
```

### Technologie-Stack

| Schicht | Technologie |
|---|---|
| Backend | Django 5.1, Django Channels, Celery + Redis |
| Frontend | HTMX 2, Alpine.js 3, SortableJS, Tailwind CSS (CDN) |
| Datenbank | SQLite (Postgres-kompatibel) |
| Prozess-Isolation | tmux via libtmux |
| Leerlauferkennung | xprintidle (X11) |
| LLM-Anbindung | Claude CLI, Anthropic API, OpenRouter, Ollama |

Kein Build-Step. Kein npm. Alles über CDN.

---

## Kernfunktionen

### 1. Kanban-Board mit Drag & Drop

Vier Spalten: **Backlog → Scheduled → In Progress → Done**. Tasks lassen sich per Drag & Drop verschieben. Wird ein Task nach "In Progress" gezogen, startet er sofort. Wird er aus "In Progress" herausgezogen, wird die laufende Ausführung abgebrochen. SortableJS steuert die Reihenfolge innerhalb der Spalten.

### 2. Leerlauferkennung (Idle Detection)

Zwei Ebenen:

- **Kurzzeit:** `xprintidle` misst die X11-Eingabe-Inaktivität in Millisekunden. Standard-Schwelle: 15 Minuten.
- **Langzeit:** Historische IdleEvents in der Datenbank erkennen längere Abwesenheiten (z. B. über Nacht), auch wenn xprintidle durch den Login zurückgesetzt wurde.

Alle 30 Sekunden wird der Idle-Status abgetastet, gespeichert und per WebSocket an das Dashboard gesendet.

### 3. Smart Scheduler

Celery Beat prüft jede Minute, ob ein Task gestartet werden soll. Der SmartScheduler durchläuft dabei eine Entscheidungskette:

1. Ist ein aktiver Schedule vorhanden?
2. Gibt es Tasks im Backlog oder Scheduled?
3. Liegt die aktuelle Uhrzeit im erlaubten Zeitfenster?
4. Ist das Token-Budget nicht erschöpft (< 95 %)?
5. Läuft gerade kein anderer Task?
6. Ist der Nutzer idle?
7. Würde die Budget-Kurve verletzt? (außer im Drain-Modus)

Nur wenn alle Bedingungen erfüllt sind, wird der nächstpriorisierte Task gestartet.

### 4. Token-Budgets mit Spending Curves

Jeder Provider hat ein konfigurierbares Wochen-Budget. Eine Budget-Kurve steuert, wie schnell Tokens verbraucht werden dürfen:

```json
[
  {"pct_week": 25, "max_pct_budget": 20},
  {"pct_week": 50, "max_pct_budget": 45},
  {"pct_week": 75, "max_pct_budget": 70}
]
```

Bedeutung: Nach 25 % der Woche dürfen maximal 20 % des Budgets verbraucht sein. Das verhindert, dass Montag früh alles aufgebraucht wird.

**Drain-Modus:** Kurz vor Ablauf einer Claude-Max-Session oder am Wochenende (> 85 % der Woche vorbei, < 70 % der Tokens verbraucht) werden die Kurven ignoriert und alle verbleibenden Tasks durchgeführt.

### 5. tmux-Integration & Live-Output

Jeder Task läuft in einem eigenen tmux-Fenster (`agentqueue:task-{id}`). Das ermöglicht:

- **Prozess-Isolation:** Tasks laufen unabhängig vom Webserver.
- **Live-Streaming:** Die Ausgabe wird per WebSocket an den Browser gestreamt und im Dashboard als scrollender Output angezeigt.
- **Jump-In:** Ein Klick kopiert den `tmux attach`-Befehl in die Zwischenablage, um direkt in die laufende Session einzusteigen.

### 6. Evergreen Tasks (Wiederkehrend)

Tasks vom Typ "Evergreen" haben eine Cron-Regel (z. B. `0 9 * * 1` = jeden Montag 9 Uhr). Nach Abschluss berechnet `croniter` den nächsten Ausführungszeitpunkt und der Task wird automatisch neu eingeplant.

### 7. Task Chains (Verkettung)

Geordnete Sequenzen von Tasks, die nacheinander ausgeführt werden. Sobald ein Schritt abgeschlossen ist, rückt die Chain vor und startet den nächsten. Celery Beat prüft alle 30 Sekunden, ob eine Chain weitergeführt werden kann.

### 8. KI-gestützte Task-Vorschläge

Der SuggestionService liest README, Git-Log und Dateistruktur eines Projekts aus und generiert per LLM fünf konkrete, autonome Aufgabenvorschläge (Titel, Prompt, Typ, Priorität, Tags). Per Klick lassen sich Vorschläge direkt ins Backlog übernehmen.

### 9. Multi-Provider-System

Vier LLM-Anbieter werden unterstützt:

| Provider | Anbindung | Voraussetzung |
|---|---|---|
| **Claude Max** | `claude` CLI als Subprocess | CLI installiert und eingeloggt |
| **Anthropic API** | Offizielles SDK (`anthropic`) | `ANTHROPIC_API_KEY` |
| **OpenRouter** | OpenAI-kompatible API | `OPENROUTER_API_KEY` |
| **Ollama** | Lokaler Server (httpx) | Ollama läuft auf Port 11434 |

Pro Projekt kann ein anderer Provider zugewiesen werden. Tasks können den Projekt-Default überschreiben.

---

## Datenmodell

### Task

Das zentrale Objekt. Felder:

- **Inhalt:** Titel, Prompt (bis 50.000 Zeichen), Tags (JSON)
- **Typ:** One-Shot, Evergreen, Chained
- **Status:** Backlog → Scheduled → In Progress → Done / Failed / Cancelled / Paused
- **Planung:** Priorität (1–4), Kanban-Reihenfolge, Cron-Regel, nächster Lauf
- **Ausführung:** tmux-Session-Name, Ergebnis-Zusammenfassung, Abschluss-Zeitpunkt
- **Zuordnung:** Projekt (FK), LLM-Config (FK, optional), Chain (FK, optional)

### TaskRun

Jede Ausführung eines Tasks wird als eigener Run gespeichert:

- Celery-Task-ID, Status, Start/Ende, Exit-Code
- Token-Verbrauch, vollständiges Output-Log, Fehler-Log
- tmux Session- und Window-Name

### TaskChain

Gruppiert Tasks zu einer geordneten Sequenz mit aktuellem Schritt.

### Project

Verweist auf ein Git-Repository (lokaler Pfad + optionale Remote-URL). Hat einen Default-Branch und eine optionale LLM-Config.

### LLMConfig

Provider-Konfiguration: Typ, API-Key, Modellname, Temperatur, Max-Tokens, System-Prompt. Genau eine Config kann als Default markiert werden.

### Schedule

Globale Scheduler-Einstellungen: Idle-Schwellen, erlaubte Uhrzeiten und Wochentage, Token-Spreading.

### TokenBudget

Pro Provider: Wochen-Limit, Reset-Tag/-Uhrzeit, Budget-Kurve, verbrauchte Tokens, Drain-Schwelle.

---

## Celery-Beat-Schedule

| Task | Intervall | Funktion |
|---|---|---|
| `sample_idle_state` | 30 s | Idle-Status abfragen und speichern |
| `check_and_trigger` | 60 s | SmartScheduler prüfen, ggf. Task starten |
| `schedule_evergreen_tasks` | 5 min | Fällige Evergreen-Tasks auf Scheduled setzen |
| `advance_chains` | 30 s | Chains vorantreiben, nächsten Schritt starten |
| `check_budget_reset` | 1 h | Wochen-Budget zurücksetzen falls fällig |

---

## Frontend

Das Frontend ist eine Single-Page-artige Anwendung ohne Build-Prozess:

- **HTMX 2** tauscht HTML-Fragmente per AJAX aus (Partials für Cards, Panels, Formulare).
- **Alpine.js 3** verwaltet den reaktiven Zustand (WebSocket-Verbindung, Idle-Status, aktive Tasks, Notifications).
- **SortableJS** ermöglicht Drag & Drop im Kanban-Board.
- **Tailwind CSS** (CDN) für das Styling.

Wichtige UI-Elemente:

- **Task-Cards:** Farbcodiert nach Status, Prioritäts-Streifen, Lauf-Animation (Glow + Scanner-Linie) bei aktiven Tasks.
- **Live-Output-Panel:** Slide-Over mit auto-scrollendem Streaming-Output.
- **Modale Formulare:** Task-Erstellung mit allen Feldern (Projekt, Prompt, Typ, Provider, etc.).
- **Keyboard-Shortcuts:** `N` = Neuer Task, `/` = Suche, `Esc` = Schließen, `?` = Hilfe.
- **Toast-Benachrichtigungen:** Erfolgs-/Fehlermeldungen.

---

## Installation & Betrieb

Voraussetzungen: Python 3.11+, Redis, tmux, xprintidle.

```bash
git clone <repo> && cd agentqueue
python -m venv .venv
cp .env.example .env      # SECRET_KEY setzen
make install               # pip install
make migrate               # SQLite-Datenbank erstellen
make setup                 # Interaktives Onboarding
```

Drei Terminals:

```bash
make dev      # Webserver → http://localhost:3333
make worker   # Celery Worker
make beat     # Celery Beat (Scheduler)
```

---

## Beispiel-Ablauf

1. **15:00** — Nutzer erstellt Task "Tests schreiben" (Evergreen, Cron: Montag 9 Uhr).
2. **15:15** — Nutzer geht in die Pause. xprintidle meldet > 15 Minuten Inaktivität.
3. **15:16** — Celery Beat feuert `check_and_trigger`. SmartScheduler prüft alle Gates: Task vorhanden, Uhrzeit erlaubt, Budget frei, kein anderer Task aktiv, Nutzer idle → Go.
4. **15:16** — TaskRunner erstellt tmux-Fenster `agentqueue:task-42`, baut den Prompt (Repo-Kontext + Task-Prompt), streamt die LLM-Ausgabe per WebSocket ans Dashboard.
5. **15:45** — LLM fertig. Output gespeichert, Tokens gezählt, Budget aktualisiert. Da Evergreen: nächster Lauf berechnet (Montag 9 Uhr), Task auf Scheduled gesetzt.
6. **16:00** — Nutzer kommt zurück, sieht den erledigten Task in der Done-Spalte.

---

## Lizenz

[Apache 2.0](LICENSE)

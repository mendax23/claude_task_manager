# AgentQueue — Projektbeschreibung

## Zusammenfassung

AgentQueue ist ein selbstgehostetes Kanban-Board mit automatischer KI-Task-Ausführung. Es erkennt, wann der Rechner im Leerlauf ist, und startet dann eigenständig KI-Aufgaben in tmux-Sessions — damit ungenutzte Claude-Max-Tokens nicht verfallen, während der Bildschirm gesperrt ist.

**Kernidee:** Aufgaben einreihen, weggehen, mit Ergebnissen zurückkommen.

---

## Architektur

### Tech-Stack

| Schicht | Technologie |
|---|---|
| Backend | Django 5.1, Django Channels, Django REST Framework |
| Task-Queue | Celery 5.4 + Redis |
| Frontend | HTMX 2, Alpine.js, SortableJS, TailwindCSS (alles via CDN) |
| Datenbank | SQLite (Postgres-ready) |
| Echtzeit | WebSockets über Django Channels |
| Task-Ausführung | tmux + libtmux |
| Idle-Erkennung | xprintidle (X11) |

Kein Build-Step. Kein npm. Rein serverseitig gerendert mit HTMX für Interaktivität.

### Django-Apps

- **core** — Abstrakte Basismodelle (`TimeStampedModel`)
- **providers** — LLM-Provider-Integrationen (Claude Max, Anthropic API, OpenRouter, Ollama)
- **projects** — Projektverwaltung mit Repo-Anbindung und KI-gestützten Aufgabenvorschlägen
- **tasks** — Aufgaben, Task-Chains, Ausführung, tmux-Management, WebSocket-Streaming
- **scheduling** — Idle-Erkennung, Token-Budgets, Smart Scheduler
- **dashboard** — Kanban-Board UI

---

## Kernfunktionen

### Kanban-Board

Vier Spalten: **Backlog → Scheduled → In Progress → Done**. Aufgaben werden per Drag-and-Drop verschoben (SortableJS). Wird eine Aufgabe nach "In Progress" gezogen, wird sie sofort gestartet. Wird sie aus "In Progress" herausgezogen, wird eine Bestätigung zum Abbrechen angezeigt.

### Idle-Erkennung

Zweischichtige Erkennung:
1. **xprintidle** — misst die X11-Eingabe-Inaktivität in Millisekunden
2. **Zeitbasiert** — prüft die IdleEvent-Historie für längere Abwesenheiten (z.B. 3+ Tage)

Wird alle 30 Sekunden abgetastet und ans Dashboard gesendet.

### Smart Scheduler

Der Scheduler prüft sechs Bedingungen, bevor eine Aufgabe gestartet wird:
1. Aufgaben in Backlog/Scheduled vorhanden
2. Innerhalb der erlaubten Zeitfenster
3. Token-Budget nicht erschöpft
4. Keine andere Aufgabe läuft bereits
5. Idle-Zustand erkannt (kurz oder lang)
6. Token-Spreading-Kurve eingehalten (nicht zu viel am Wochenanfang verbrauchen)

**Drain-Modus:** Wenn die Session abläuft oder >85% der Woche vorbei sind, werden die Budgetgrenzen gelockert, um verbleibende Tokens noch zu nutzen.

### Token-Budget-Verwaltung

- Wöchentliche Limits pro Provider
- Konfigurierbare Spending-Kurve verhindert frühzeitiges Überverbrauchen
- Automatischer Reset nach konfigurierbarem Wochentag und Uhrzeit
- Session-Tracking mit Ablaufzeit

### Task-Ausführung

1. Aufgabe wird gestartet (manuell oder automatisch)
2. tmux-Fenster wird erstellt
3. Prompt wird gebaut (Repo-Kontext aus README + Git-Log + Aufgaben-Prompt)
4. LLM-Ausgabe wird gestreamt an:
   - Temporäre Datei (für tmux-Anzeige)
   - WebSocket → Dashboard (Live-Updates im Browser)
5. Ergebnis wird als `TaskRun` gespeichert (Token-Verbrauch, Ausgabe, Fehler)
6. Bei Evergreen-Tasks: automatische Neuplanung
7. Bei Task-Chains: nächster Schritt wird ausgelöst

### Evergreen-Tasks

Wiederkehrende Aufgaben mit Cron-Ausdruck (z.B. `0 9 * * 1` = montags um 9 Uhr). Nach jeder Ausführung wird der Task automatisch mit neuem `next_run_at` zurück in den Backlog verschoben.

### Task-Chains

Geordnete Sequenzen von Aufgaben, die Schritt für Schritt abgearbeitet werden. Wenn alle Tasks eines Schritts erledigt sind, wird automatisch der nächste Schritt gestartet.

### KI-Aufgabenvorschläge

Liest das README und den Git-Log eines Projekts und generiert per LLM fünf konkrete, autonome Coding-Aufgaben mit Titel, Prompt, Typ, Priorität und Tags.

---

## LLM-Provider

| Provider | Authentifizierung | Besonderheit |
|---|---|---|
| **Claude Max** | `claude` CLI (eingeloggt) | Subprocess-Wrapper, kein API-Key nötig |
| **Anthropic API** | `ANTHROPIC_API_KEY` | Offizielles Python SDK |
| **OpenRouter** | `OPENROUTER_API_KEY` | 100+ Modelle über OpenAI-kompatible API |
| **Ollama** | Keine (lokal) | Lokale Modelle, Standard: llama3 |

Alle Provider unterstützen Streaming, Health-Checks, Token-Schätzung und Retry-Logik mit exponentiellem Backoff. Pro Projekt kann ein eigener Provider konfiguriert werden.

---

## Celery-Tasks (Hintergrundprozesse)

| Task | Intervall | Zweck |
|---|---|---|
| `sample_idle_state` | 30s | Idle-Status abtasten und ans Dashboard senden |
| `check_and_trigger` | 60s | Smart Scheduler ausführen, ggf. Task starten |
| `schedule_evergreen_tasks` | 5 min | Evergreen-Tasks mit fälligem `next_run_at` in Scheduled verschieben |
| `advance_chains` | 30s | Nächsten Chain-Schritt starten, wenn aktueller erledigt |
| `check_budget_reset` | 1 Std | Wöchentliche Token-Zähler zurücksetzen |

---

## WebSocket-Events

- `task_update` — Statusänderungen (gestartet, erledigt, fehlgeschlagen)
- `idle_update` — Idle-Zustand (Millisekunden, Quelle)
- `budget_update` — Token-Budget geändert
- `output_chunk` — Gestreamte LLM-Ausgabe
- `notification` — Toast-Benachrichtigungen

---

## Systemvoraussetzungen

- Python 3.11+
- Redis
- tmux
- xprintidle
- Linux mit X11 (für Idle-Erkennung)

---

## Entwicklung

```bash
make install    # Abhängigkeiten installieren
make migrate    # Datenbank erstellen
make setup      # Interaktives Onboarding

# Drei Terminals:
make dev        # Webserver → http://localhost:3333
make worker     # Celery Worker
make beat       # Celery Scheduler
```

---

## Designprinzipien

- **Kein Build-Step** — JS/CSS komplett über CDN
- **Django-nativ** — Kein separates Frontend-Framework
- **Localhost-first** — Selbstgehostet, keine Cloud-Abhängigkeit
- **Token-bewusst** — Budgets und Spreading verhindern Verschwendung
- **Idle-gesteuert** — Startet Aufgaben erst bei Inaktivität
- **Live-Streaming** — Echtzeit-Ausgabe in tmux und Browser

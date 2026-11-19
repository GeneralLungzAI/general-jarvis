# General JARVIS

General JARVIS is a Telegram-based AI assistant built to grow into an authorised operational assistant for GeneralLungz.

## Current capabilities

- Conversational AI through the OpenAI Responses API.
- Telegram commands for task management.
- PostgreSQL/Neon-backed tasks, conversation history, and long-term memory (user-scoped).
- Tasks are scoped to the Telegram user who created them.

## Telegram task commands

- `/addtask <task>` — save a task.
- `/tasks` — list pending tasks.
- `/done <id>` — mark a pending task complete.
- `/completed` — list completed tasks.
- `/deltask <id>` — delete a task.
- `/reset` — clear temporary conversation history only; saved tasks are not deleted.

## Environment variables

- `TELEGRAM_BOT_TOKEN` — Telegram bot token.
- `OPENAI_API_KEY` — OpenAI API key.
- `PORT` — web service port (defaults to 10000).
- `JARVIS_DB_PATH` — SQLite database file path (defaults to `jarvis.db`).

## Persistence note

SQLite data survives application restarts only if the database file is on persistent storage. On hosting platforms with ephemeral filesystems, configure a persistent disk or move the task database to a managed database before relying on it for important tasks.

## Safety

JARVIS must not perform consequential external actions without explicit authorisation. Task management commands only affect tasks belonging to the Telegram account that issued them.


## TradingView webhook integration

JARVIS exposes `POST /tradingview/webhook` for authenticated EURUSD event ingestion. Configure the Render environment variable `TRADINGVIEW_WEBHOOK_SECRET` before enabling alerts. Send it in the JSON body as `secret`; never put broker credentials, account passwords, or API keys in an alert body. The endpoint stores validated, deduplicated events in Neon and does not place trades.

Accepted timeframes are `1`, `3`, `5`, `15`, `60`, and `240` minutes. Accepted event types are `structure_candidate`, `displacement_candidate`, and `context_update`. TradingView alerts should use confirmed-bar logic and once-per-bar-close frequency for structure/displacement events. Webhook delivery is not guaranteed; monitor TradingView's alert log and JARVIS's event logs. Do not treat a successful HTTP receipt as a validated trade setup.

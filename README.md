# General JARVIS

General JARVIS is a Telegram-based AI assistant being developed into an authorised operational assistant for GeneralLungz.

## Current capabilities

- Conversational AI through the OpenAI Responses API.
- Telegram task management and commands.
- Neon/PostgreSQL-backed tasks, conversation history, long-term memory, and TradingView event inbox.
- User-scoped task and memory records.
- Authenticated TradingView webhook ingestion with duplicate-event protection.
- Deterministic closed-bar SMC research primitives in `smc_engine.py`.

## Telegram commands

- `/addtask <task>` — save a task.
- `/tasks` — list pending tasks.
- `/done <id>` — mark a pending task complete.
- `/completed` — list completed tasks.
- `/deltask <id>` — delete a task.
- `/remember <category> | <fact>` — save long-term memory.
- `/memories` — list saved long-term memories.
- `/forget <id>` — delete one saved memory.
- `/reset` — clear conversation history only; saved tasks and long-term memories remain intact.

## Environment variables

- `TELEGRAM_BOT_TOKEN` — Telegram bot token.
- `OPENAI_API_KEY` — OpenAI API key.
- `DATABASE_URL` — Neon/PostgreSQL connection string.
- `TRADINGVIEW_WEBHOOK_SECRET` — private webhook secret; configure in Render and in the TradingView bridge's private input.
- `PORT` — web service port (Render supplies this).

## TradingView OHLC bridge

Pine Script source: `tradingview/general_jarvis_ohlc_bridge.pine`.

1. Set a strong random secret in Render as `TRADINGVIEW_WEBHOOK_SECRET`. Do not send it in chat or commit it to the repository.
2. Add the Pine Script to TradingView Pine Editor and save it as a private script.
3. Add it to an EURUSD chart. Create one alert using **Any alert() function call**.
4. Set the alert webhook URL to `https://general-jarvis.onrender.com/tradingview/webhook`.
5. Enter the same secret in the script's input. Use one chart/alert per timeframe: 1m, 3m, 5m, 15m, 1h and 4h.
6. Confirm webhook delivery in TradingView's alert log and confirm event receipt in Render logs.

The bridge sends only confirmed chart bars and includes the event ID, EURUSD symbol, timeframe, Unix bar-close time, and OHLC. The server validates the symbol, timeframe, payload, OHLC envelope, and secret before storing the event in Neon. Duplicate event IDs are ignored.

The TradingView webhook is an ingestion endpoint, not a trade signal or execution endpoint. The SMC engine still requires independent H4 bias, M15 POI/liquidity context, event freshness, and historical calibration before any setup can be considered. No orders are sent to FTMO or any broker.

TradingView webhook delivery can fail or time out. Monitor both TradingView's alert log and JARVIS's Render logs; do not interpret an alert configured in TradingView as proof that JARVIS received it.

## SMC engine status

The current Python engine is deterministic research scaffolding. It uses confirmed pivots, closed-bar structure breaks, ATR-normalised displacement measurements, and an M1 MSS trigger with M3/M5 support under H4 directional alignment. Unknown prior trend is not guessed to be MSS. A live, validated signal additionally needs H4 structure state, M15 POI/liquidity and session/news gates, freshness/expiry rules, broker-feed data, and out-of-sample calibration.

Default displacement thresholds are experimental starting values, not proven profitable parameters. Do not tune them to one attractive chart or treat unit tests as evidence of trading edge.

## Safety

JARVIS is analysis and alerting only. It must not place trades, access FTMO credentials, or execute consequential external actions without separate explicit authorisation. Trading remains manual.

# General JARVIS — TradingView setup and acceptance checklist

## TradingView bridge setup

The repository bridge is `tradingview/general_jarvis_ohlc_bridge.pine`. It is a webhook bridge and SMC candidate detector; it is not a replacement for or an assertion that the user's separate **MV 3.2 SMC ENGINE** source has been compiled.

1. In Render, open the `general-jarvis` service and Environment.
2. Confirm `TRADINGVIEW_WEBHOOK_SECRET` exists. Keep its value private.
3. In TradingView, open Pine Editor and add the bridge source as a private indicator.
4. On the indicator's settings, enter the exact Render secret in **Webhook secret (32+ random characters)**. Do not paste the secret into a public script, screenshot, issue, or commit.
5. Add the indicator to EURUSD charts for each timeframe: 1m, 3m, 5m, 15m, 1h and 4h.
6. On the EURUSD chart, open **Create alert**. Choose this bridge indicator in **Condition**, then choose **Any alert() function call**.
7. Open the alert's **Notifications** options, enable **Webhook URL**, and enter:
   `https://general-jarvis.onrender.com/tradingview/webhook`
8. Leave the message field alone; the Pine `alert()` call supplies the dynamic JSON body. Create the alert and repeat for each timeframe: 1m, 3m, 5m, 15m, 1h and 4h.
9. Confirm the alert is active. Check the TradingView alert log's webhook status, then Render logs for `TRADINGVIEW_EVENT_QUEUED` and `TRADINGVIEW_EVENT_PROCESSED`.

The bridge uses `alert.freq_once_per_bar_close`; the dialog's frequency setting does not override the Pine call. Webhook alerts require TradingView two-factor authentication. Each alert stores a snapshot of the script and chart settings, so recreate alerts after changing the script or its inputs.

On iPhone, use the chart's alert/bell control, choose **Create alert**, and select the indicator condition. If the webhook option is unavailable, finish setup in TradingView's web chart after enabling two-factor authentication.

## Event and POI lifecycle

- Every authenticated closed EURUSD bar is stored with a deterministic event ID; duplicate event IDs are idempotently ignored.
- The webhook acknowledges quickly; a durable Neon queue processes SMC work outside TradingView's three-second webhook timeout.
- POI, mitigation, invalidation and LTF-confirmation Telegram notices are written to a durable outbox and retried until delivered or the retry limit is reached.
- Only a qualified M15 POI candidate aligned with H4 bias is inserted into the POI table.
- M1/M3/M5 bars are stored separately for post-mitigation analysis.
- A closed LTF bar overlapping the active OB or IMB marks the POI mitigated.
- A close beyond the OB invalidates the POI; a confirmed H4 bias reversal also invalidates it.
- Post-mitigation confirmation requires an established pre-mitigation M1 trend, a post-mitigation M1 MSS with displacement in the H4/POI direction, and eligible M3 and M5 directional support.
- A confirmation is an alert-only research candidate. No order is sent.

## Current safety limits

- H4 remains authoritative; an M15/LTF reaction cannot reverse it.
- One active qualified M15 POI is maintained by the store.
- No standalone imbalance is promoted to a POI.
- Unknown M1 prior trend fails closed; it is not guessed to be an MSS.
- Session/news gates and strategy calibration remain separate validation requirements. The Tokyo window in the Pine bridge defaults to 00:00–06:00 Asia/Tokyo and must match the user's intended session configuration.
- No automatic trade execution, FTMO access, or broker order endpoints.

## Acceptance checks

1. GitHub Actions Python compile and unit tests pass.
2. Render latest deploy is live and `/health` reports Telegram, webhook secret, and processor readiness.
3. If `telegram_chat_configured` is false on `/health`, send `/chatid` to the bot and set the returned value as `TELEGRAM_CHAT_ID` in Render Environment, then allow the service to redeploy.
5. Telegram `/tasks`, `/addtask`, `/done`, `/remember`, and `/memories` work with persistent Neon records.
6. A TradingView alert delivers a confirmed EURUSD bar and Render logs show it queued and processed.
5. A valid M15 POI is persisted once; a duplicate webhook does not create a second record.
6. A replayed LTF bar marks mitigation; invalidation and LTF confirmation paths are exercised in a controlled test.
7. Telegram receives the POI, mitigation, invalidation, and confirmation alerts.
8. A service restart does not erase tasks or long-term memories.

A live TradingView alert and Telegram recipient are account-level configuration. Do not mark those checks passed until the user has configured and observed them.

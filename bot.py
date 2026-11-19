import os
import json
import asyncio
import threading
import urllib.request
import urllib.error
import traceback

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from task_store import (
    initialize as initialize_task_store,
    add_task,
    list_tasks,
    complete_task,
    delete_task,
    acquire_telegram_polling_lock,
    start_telegram_lock_heartbeat,
    release_telegram_polling_lock,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = "gpt-4.1-mini"

app = Flask(__name__)

SYSTEM_PROMPT = """
You are GENERAL JARVIS, the AI assistant of GeneralLungz.

Your personality:
- Intelligent, composed, respectful and precise.
- Address the user as General when natural.
- Explain technical matters clearly.
- Be honest about your capabilities.
- Never claim to have performed an action you have not performed.
- Ask for confirmation before sensitive actions.
- You are an assistant, not an autonomous authority.
"""


@app.route("/")
def home():
    return "GENERAL JARVIS IS ONLINE"


def ask_openai(history):
    payload = {
        "model": MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": history,
        "max_output_tokens": 700
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        print("OPENAI HTTP ERROR:", error.code, details, flush=True)
        raise

    except urllib.error.URLError as error:
        print("OPENAI CONNECTION ERROR:", str(error.reason), flush=True)
        raise

    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")

    print("OPENAI RESPONSE:", json.dumps(result), flush=True)
    return "I couldn't generate a response. Please try again, General."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []
    await update.message.reply_text(
        "GENERAL JARVIS ONLINE.\n"
        "Telegram connection established.\n"
        "Task memory is ready.\n"
        "Awaiting instructions, General."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[JARVIS] COMMAND_HANDLER help update_id={update.update_id}", flush=True)
    await update.message.reply_text(
        "GENERAL JARVIS COMMANDS\n\n"
        "/start - Initialize Jarvis\n"
        "/help - Show commands\n"
        "/reset - Clear conversation memory\n"
        "/addtask <task> - Save a task\n"
        "/tasks - Show pending tasks\n"
        "/done <id> - Mark a task complete\n"
        "/completed - Show completed tasks\n"
        "/deltask <id> - Delete a task"
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []
    await update.message.reply_text(
        "Conversation memory cleared, General. Saved tasks remain intact."
    )


async def addtask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = " ".join(context.args).strip()
    if not title:
        await update.message.reply_text(
            "Give me a task to save. Example: /addtask Prepare the project roadmap"
        )
        return

    try:
        task_id = add_task(update.effective_user.id, title)
        await update.message.reply_text(
            f"Task saved, General.\nID: {task_id}\n{title}"
        )
    except ValueError as error:
        await update.message.reply_text(str(error))


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[JARVIS] COMMAND_HANDLER tasks update_id={update.update_id}", flush=True)
    tasks = list_tasks(update.effective_user.id, "pending")
    if not tasks:
        await update.message.reply_text("No pending tasks, General.")
        return

    lines = ["PENDING TASKS"]
    lines.extend(f"#{task['id']} — {task['title']}" for task in tasks)
    await update.message.reply_text("\n".join(lines))


async def completed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = list_tasks(update.effective_user.id, "completed")
    if not tasks:
        await update.message.reply_text("No completed tasks recorded yet.")
        return

    lines = ["COMPLETED TASKS"]
    lines.extend(f"#{task['id']} — {task['title']}" for task in tasks)
    await update.message.reply_text("\n".join(lines))


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /done <task_id>")
        return

    task_id = int(context.args[0])
    if complete_task(update.effective_user.id, task_id):
        await update.message.reply_text(f"Task #{task_id} marked complete.")
    else:
        await update.message.reply_text(
            "I couldn't find that pending task in your task list."
        )


async def deltask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /deltask <task_id>")
        return

    task_id = int(context.args[0])
    if delete_task(update.effective_user.id, task_id):
        await update.message.reply_text(f"Task #{task_id} deleted.")
    else:
        await update.message.reply_text(
            "I couldn't find that task in your task list."
        )


async def respond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[JARVIS] TEXT_HANDLER update_id={update.update_id}", flush=True)
    message = update.message.text.strip()
    if not message:
        return

    await update.message.chat.send_action("typing")
    history = context.user_data.setdefault("history", [])
    history.append({"role": "user", "content": message})

    try:
        answer = await asyncio.to_thread(ask_openai, history[-12:])
        history.append({"role": "assistant", "content": answer})
        context.user_data["history"] = history[-12:]
        await update.message.reply_text(answer)

    except urllib.error.HTTPError:
        await update.message.reply_text(
            "My intelligence service returned an error, General. "
            "Please check system diagnostics."
        )

    except Exception as error:
        print("GENERAL JARVIS ERROR:", repr(error), flush=True)
        await update.message.reply_text(
            "An internal connection error occurred, General."
        )


async def telegram_post_init(application: Application):
    bot_info = await application.bot.get_me()
    print(
        f"[JARVIS] Telegram authenticated as @{bot_info.username} "
        f"(bot_id={bot_info.id}).",
        flush=True
    )


def run_bot():
    print("[JARVIS] Telegram worker starting.", flush=True)
    try:
        if not TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is missing.")

        print("[JARVIS] Initializing Neon task database...", flush=True)
        initialize_task_store()
        print("[JARVIS] Neon task database initialized successfully.", flush=True)

        application = (
            Application.builder()
            .token(TOKEN)
            .post_init(telegram_post_init)
            .build()
        )
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("reset", reset_command))
        application.add_handler(CommandHandler("addtask", addtask_command))
        application.add_handler(CommandHandler("tasks", tasks_command))
        application.add_handler(CommandHandler("completed", completed_command))
        application.add_handler(CommandHandler("done", done_command))
        application.add_handler(CommandHandler("deltask", deltask_command))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, respond)
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        polling_lock_connection = acquire_telegram_polling_lock()
        heartbeat = start_telegram_lock_heartbeat(polling_lock_connection)

        try:
            print("[JARVIS] Starting Telegram polling...", flush=True)
            application.run_polling(stop_signals=None)
        finally:
            release_telegram_polling_lock(polling_lock_connection, *heartbeat)

    except Exception as error:
        print(
            f"[JARVIS] Telegram worker stopped with "
            f"{type(error).__name__}: {error}",
            flush=True
        )
        traceback.print_exc()
        raise


def start_telegram_worker():
    worker = threading.Thread(
        target=run_bot,
        name="telegram-worker",
        daemon=True
    )
    worker.start()
    return worker


if __name__ == "__main__":
    # Preserve Render's existing start command while replacing Flask's
    # development server with Gunicorn.
    port = os.environ.get("PORT", "10000")
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "--workers", "1",
            "--threads", "4",
            "--bind", f"0.0.0.0:{port}",
            "--access-logfile", "-",
            "bot:app",
        ],
    )
else:
    # Gunicorn imports this module as "bot"; start exactly one Telegram
    # worker inside its single WSGI worker process.
    start_telegram_worker()


import os
import asyncio
import threading

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

app = Flask(__name__)


@app.route("/")
def home():
    return "GENERAL JARVIS IS ONLINE"


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "GENERAL JARVIS ONLINE.\n"
        "Systems initialized.\n"
        "Awaiting instructions."
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "GENERAL JARVIS COMMANDS\n\n"
        "/start - Initialize Jarvis\n"
        "/help - Show available commands\n\n"
        "AI intelligence integration is the next stage."
    )


async def respond(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "Message received, General.\n"
        "My AI intelligence module is not connected yet."
    )


def run_bot():
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable is missing."
        )

    # Create an event loop for this background thread.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = Application.builder().token(TOKEN).build()

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            respond
        )
    )

    application.run_polling(stop_signals=None)


if __name__ == "__main__":
    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )

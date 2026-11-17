
import os
import json
import asyncio
import threading
import urllib.request
import urllib.error

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
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = "gpt-4.1-mini"

app = Flask(__name__)

SYSTEM_PROMPT = """
You are GENERAL JARVIS, the AI assistant of GeneralLungz.

Your personality:
- Intelligent, composed, respectful and precise.
- Address the user as General when natural.
- Explain technical matters clearly.
- Be honest about what you can and cannot do.
- Never claim to have executed an action you have not performed.
- Ask for confirmation before sensitive actions.
- You are an assistant, not an autonomous authority.
"""


@app.route("/")
def home():
    return "GENERAL JARVIS IS ONLINE"


def ask_openai(history):
    payload = {
        "model": MODEL,
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

    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))

    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")

    return "I couldn't generate a response. Please try again, General."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []

    await update.message.reply_text(
        "GENERAL JARVIS ONLINE.\n"
        "AI intelligence module connected.\n"
        "Systems initialized.\n"
        "Awaiting instructions, General."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "GENERAL JARVIS COMMANDS\n\n"
        "/start - Initialize Jarvis and reset chat memory\n"
        "/help - Show available commands\n"
        "/reset - Clear conversation memory\n\n"
        "AI intelligence is online."
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []
    await update.message.reply_text(
        "Conversation memory cleared, General."
    )


async def respond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()

    if not message:
        return

    await update.message.chat.send_action("typing")

    history = context.user_data.setdefault("history", [])

    history.append({
        "role": "user",
        "content": message
    })

    conversation = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ] + history[-12:]

    try:
        answer = await asyncio.to_thread(
            ask_openai,
            conversation
        )

        history.append({
            "role": "assistant",
            "content": answer
        })

        context.user_data["history"] = history[-12:]

        await update.message.reply_text(answer)

    except urllib.error.HTTPError as error:
        print("OpenAI HTTP error:", error.code)
        await update.message.reply_text(
            "I'm having trouble connecting to my intelligence service, General. Please try again shortly."
        )

    except Exception as error:
        print("AI error:", str(error))
        await update.message.reply_text(
            "An internal error occurred. My systems are still online, General."
        )


def run_bot():
    if not TOKEN:
        raise RuntimeError("Telegram token is missing.")

    if not OPENAI_API_KEY:
        raise RuntimeError("OpenAI API key is missing.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, respond)
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

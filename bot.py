import os
import logging
from collections import defaultdict

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from openai import OpenAI

# ---------- Настройка ----------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()  # подхватывает .env файл, если он есть рядом с bot.py

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
# Бесплатные модели OpenRouter помечены суффиксом ":free".
# Список бесплатных моделей периодически меняется — актуальный смотрите на
# https://openrouter.ai/models?max_price=0
MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
SYSTEM_PROMPT = (
    "Ты дружелюбный ИИ-ассистент в Telegram. Отвечай кратко и по делу, "
    "используй простой и понятный язык. Отвечай на том языке, на котором "
    "пишет пользователь."
)
MAX_HISTORY_MESSAGES = 20  # сколько последних сообщений помнить на пользователя
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))  # длина ответа ИИ
TELEGRAM_MSG_LIMIT = 4096  # жёсткий лимит Telegram на длину одного сообщения

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Простая память диалога в оперативной памяти процесса (сбрасывается при рестарте бота)
chat_histories: dict[int, list[dict]] = defaultdict(list)


# ---------- Обработчики команд ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_histories[update.effective_chat.id].clear()
    await update.message.reply_text(
        "Привет! Я бесплатный ИИ-ассистент. Просто напиши мне вопрос — "
        "отвечу как обычный ИИ-чат. Команда /reset очищает историю диалога."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_histories[update.effective_chat.id].clear()
    await update.message.reply_text("История диалога очищена.")


# ---------- Обработка обычных сообщений ----------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    history = chat_histories[chat_id]
    history.append({"role": "user", "content": user_text})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history],
        )
        reply_text = (response.choices[0].message.content or "").strip() or (
            "Извини, не получилось сформулировать ответ."
        )
    except Exception:
        logger.exception("Ошибка запроса к OpenRouter API")
        reply_text = (
            "Произошла ошибка при обращении к ИИ (возможно, бесплатная модель "
            "сейчас перегружена — попробуй ещё раз через минуту)."
        )
        # не сохраняем неудачный обмен в историю
        history.pop()
    else:
        history.append({"role": "assistant", "content": reply_text})

    for i in range(0, len(reply_text), TELEGRAM_MSG_LIMIT):
        await update.message.reply_text(reply_text[i : i + TELEGRAM_MSG_LIMIT])


# ---------- Точка входа ----------

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен и слушает сообщения...")
    app.run_polling()


if __name__ == "__main__":
    main()

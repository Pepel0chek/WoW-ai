import os
import logging
import random
from collections import defaultdict

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from openai import OpenAI

# ---------- Настройка ----------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
SYSTEM_PROMPT = (
    "Ты дружелюбный ИИ-ассистент в Telegram. Отвечай кратко и по делу, "
    "используй простой и понятный язык. Отвечай на том языке, на котором "
    "пишет пользователь."
)
MAX_HISTORY_MESSAGES = 20
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))
TELEGRAM_MSG_LIMIT = 4096

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# ---------- Хранилища ----------
chat_histories: dict[int, list[dict]] = defaultdict(list)
player_stats = {}
ai_games = {}
user_modes = {}

BOT_USERNAME = None

# ========== ИНИЦИАЛИЗАЦИЯ ==========
def init_player(user_id, name):
    if user_id not in player_stats:
        player_stats[user_id] = {
            "name": name,
            "wins": 0,
            "losses": 0,
            "games": {
                "roulette": {"wins": 0, "losses": 0},
                "guess": {"wins": 0, "losses": 0},
                "cards": {"wins": 0, "losses": 0},
                "darts": {"wins": 0, "losses": 0},
                "blackjack": {"wins": 0, "losses": 0}
            }
        }

# ========== СТАРТ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Бот работает!\n"
        "В группе пиши @имя_бота [текст]\n"
        "В личке пиши просто текст\n\n"
        "Режимы:\n"
        "@имя_бота games — игры\n"
        "@имя_бота AI — ИИ-чат"
    )

# ========== ОБРАБОТКА УПОМИНАНИЙ ==========
async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_text = update.message.text or ""
    
    global BOT_USERNAME
    if BOT_USERNAME is None:
        bot_info = await context.bot.get_me()
        BOT_USERNAME = bot_info.username
    
    clean_text = user_text
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "mention":
                mention = user_text[entity.offset:entity.offset + entity.length]
                clean_text = clean_text.replace(mention, "").strip()
            elif entity.type == "text_mention":
                clean_text = clean_text.replace(f"@{BOT_USERNAME}", "").strip()
    
    if not clean_text:
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n\n"
            f"Режимы:\n"
            f"• `@{BOT_USERNAME} AI` — режим ИИ-чата\n"
            f"• `@{BOT_USERNAME} games` — режим игр\n"
            f"• `@{BOT_USERNAME} [текст]` — ответ в текущем режиме\n\n"
            f"Твой текущий режим: {get_mode_text(user.id)}"
        )
        return
    
    parts = clean_text.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    
    if command == "ai":
        user_modes[user.id] = "ai"
        await update.message.reply_text(
            f"🤖 Режим **ИИ** активирован!\n"
            f"Теперь я буду отвечать как умный ассистент.\n"
            f"Просто пиши: `@{BOT_USERNAME} [вопрос]`"
        )
        return
    
    elif command == "games":
        user_modes[user.id] = "games"
        await show_games_menu(update, context)
        return
    
    mode = user_modes.get(user.id, "ai")
    
    if mode == "ai":
        await handle_ai_response(update, context, clean_text)
    
    elif mode == "games":
        if command == "roulette":
            await play_roulette(update, context)
        elif command == "guess":
            await play_guess(update, context)
        elif command == "cards":
            await play_cards(update, context)
        elif command == "darts":
            await play_darts(update, context)
        elif command == "blackjack":
            await play_blackjack(update, context)
        elif command == "stats":
            await show_stats(update, context)
        elif command == "rating":
            await show_rating(update, context)
        elif command == "help":
            await show_games_help(update, context)
        else:
            if user.id in ai_games and ai_games[user.id]["type"] == "guess":
                await process_guess(update, context, clean_text)
            else:
                await show_games_menu(update, context)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_mode_text(user_id):
    mode = user_modes.get(user_id, "ai")
    return "🤖 ИИ" if mode == "ai" else "🎮 Игры"

async def show_games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = BOT_USERNAME or "бот"
    
    await update.message.reply_text(
        f"🎮 **Режим игр**\n\n"
        f"Доступные команды:\n"
        f"• `@{bot_name} roulette` — 🔫 Русская рулетка\n"
        f"• `@{bot_name} guess` — 🎲 Угадай число\n"
        f"• `@{bot_name} cards` — 🃏 Карточная игра\n"
        f"• `@{bot_name} darts` — 🎯 Дартс\n"
        f"• `@{bot_name} blackjack` — 🃏 Блэкджек 21\n"
        f"• `@{bot_name} stats` — 📊 Моя статистика\n"
        f"• `@{bot_name} rating` — 🏆 Рейтинг\n"
        f"• `@{bot_name} help` — ❓ Помощь\n\n"
        f"Или просто напиши число для 'Угадай число'"
    )

async def show_games_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = BOT_USERNAME or "бот"
    await update.message.reply_text(
        f"❓ **Помощь по играм**\n\n"
        f"🔫 **Русская рулетка** — `@{bot_name} roulette`\n"
        f"   Стреляй против ИИ, шанс 1 к 6\n\n"
        f"🎲 **Угадай число** — `@{bot_name} guess`\n"
        f"   Угадай число от 1 до 10, 3 попытки\n\n"
        f"🃏 **Карточная игра** — `@{bot_name} cards`\n"
        f"   Тяни карту против ИИ\n\n"
        f"🎯 **Дартс** — `@{bot_name} darts`\n"
        f"   Бросай дротик против ИИ\n\n"
        f"🃏 **Блэкджек 21** — `@{bot_name} blackjack`\n"
        f"   Играй в 21 против ИИ\n\n"
        f"📊 **Статистика** — `@{bot_name} stats`\n"
        f"🏆 **Рейтинг** — `@{bot_name} rating`"
    )

# ============================================
# 🎮 ИГРЫ
# ============================================

# 🔫 РУССКАЯ РУЛЕТКА
async def play_roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_player(user.id, user.first_name)
    
    chamber = random.randint(1, 6)
    shot = random.randint(1, 6)
    
    if shot == chamber:
        player_stats[user.id]["games"]["roulette"]["losses"] += 1
        player_stats[user.id]["losses"] += 1
        result = f"💥 **БАХ!** Патрон был в барабане!\n😵 Ты проиграл!"
    else:
        player_stats[user.id]["games"]["roulette"]["wins"] += 1
        player_stats[user.id]["wins"] += 1
        result = f"✨ **Клик!** Пусто!\n🎉 Ты выжил!"
    
    ai_shot = random.randint(1, 6)
    ai_result = "💀 ИИ проиграл!" if ai_shot == chamber else "🎉 ИИ выжил!"
    
    await update.message.reply_text(
        f"🔫 **Русская рулетка**\n\n"
        f"Твой выстрел: {result}\n"
        f"Выстрел ИИ: {ai_result}\n\n"
        f"🎯 Шанс был 1 к 6!"
    )

# 🎲 УГАДАЙ ЧИСЛО
async def play_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_player(user.id, user.first_name)
    
    number = random.randint(1, 10)
    ai_games[user.id] = {"type": "guess", "number": number, "attempts": 0, "max": 3}
    
    await update.message.reply_text(
        f"🎲 **Угадай число**\n\n"
        f"Я загадал число от 1 до 10.\n"
        f"Напиши `@{BOT_USERNAME} [число]`\n"
        f"(У тебя 3 попытки)\n\n"
        f"🤖 ИИ тоже будет угадывать!"
    )

async def process_guess(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user
    init_player(user.id, user.first_name)
    
    try:
        guess_num = int(text)
        game = ai_games[user.id]
        
        if guess_num < 1 or guess_num > 10:
            await update.message.reply_text("⚠️ Число должно быть от 1 до 10!")
            return
        
        game["attempts"] += 1
        
        if guess_num == game["number"]:
            player_stats[user.id]["games"]["guess"]["wins"] += 1
            player_stats[user.id]["wins"] += 1
            await update.message.reply_text(
                f"🎉 **Ты угадал число {game['number']}!**\n"
                f"Попыток: {game['attempts']}\n"
                f"🏆 Поздравляем!"
            )
            del ai_games[user.id]
            return
        elif game["attempts"] >= 3:
            player_stats[user.id]["games"]["guess"]["losses"] += 1
            player_stats[user.id]["losses"] += 1
            await update.message.reply_text(
                f"😢 Попытки закончились! Число было **{game['number']}**\n"
                f"Попробуй снова: `@{BOT_USERNAME} guess`"
            )
            del ai_games[user.id]
            return
        elif guess_num < game["number"]:
            await update.message.reply_text(f"📈 {guess_num} — **больше!** (осталось {3 - game['attempts']} попыток)")
        else:
            await update.message.reply_text(f"📉 {guess_num} — **меньше!** (осталось {3 - game['attempts']} попыток)")
            
        if user.id in ai_games:
            ai_guess = random.randint(1, 10)
            if ai_guess == game["number"]:
                await update.message.reply_text(
                    f"🤖 ИИ угадал число {game['number']}!\n"
                    f"😅 В этот раз удача на стороне ИИ!"
                )
                player_stats[user.id]["games"]["guess"]["losses"] += 1
                player_stats[user.id]["losses"] += 1
                del ai_games[user.id]
            
    except ValueError:
        await update.message.reply_text("⚠️ Введи ЧИСЛО от 1 до 10!")

# 🃏 КАРТОЧНАЯ ИГРА
async def play_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_player(user.id, user.first_name)
    
    cards = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    suits = ["♠", "♥", "♦", "♣"]
    deck = [f"{c}{s}" for c in cards for s in suits]
    
    player_card = random.choice(deck)
    ai_card = random.choice(deck)
    
    values = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
    p_val = values[player_card[:-1]]
    ai_val = values[ai_card[:-1]]
    
    if p_val > ai_val:
        player_stats[user.id]["games"]["cards"]["wins"] += 1
        player_stats[user.id]["wins"] += 1
        result = f"🎉 Ты выиграл!"
    elif p_val < ai_val:
        player_stats[user.id]["games"]["cards"]["losses"] += 1
        player_stats[user.id]["losses"] += 1
        result = f"😢 Ты проиграл!"
    else:
        result = f"🤝 Ничья!"
    
    await update.message.reply_text(
        f"🃏 **Карточная игра**\n\n"
        f"Твоя карта: **{player_card}**\n"
        f"Карта ИИ: **{ai_card}**\n\n"
        f"{result}"
    )

# 🎯 ДАРТС
async def play_darts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_player(user.id, user.first_name)
    
    target = random.randint(1, 10)
    player_throw = random.randint(1, 10)
    ai_throw = random.randint(1, 10)
    
    player_diff = abs(target - player_throw)
    ai_diff = abs(target - ai_throw)
    
    if player_diff < ai_diff:
        player_stats[user.id]["games"]["darts"]["wins"] += 1
        player_stats[user.id]["wins"] += 1
        result = f"🎯 Ты победил!"
    elif player_diff > ai_diff:
        player_stats[user.id]["games"]["darts"]["losses"] += 1
        player_stats[user.id]["losses"] += 1
        result = f"😢 Ты проиграл!"
    else:
        result = f"🤝 Ничья!"
    
    await update.message.reply_text(
        f"🎯 **Дартс**\n\n"
        f"Твой бросок: {player_throw}\n"
        f"Бросок ИИ: {ai_throw}\n"
        f"Цель: {target}\n\n"
        f"{result}"
    )

# 🃏 БЛЭКДЖЕК 21
async def play_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_player(user.id, user.first_name)
    
    cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11]
    
    player_hand = [random.choice(cards), random.choice(cards)]
    ai_hand = [random.choice(cards), random.choice(cards)]
    
    player_sum = sum(player_hand)
    ai_sum = sum(ai_hand)
    
    while ai_sum < 17:
        ai_hand.append(random.choice(cards))
        ai_sum = sum(ai_hand)
        if ai_sum > 21 and 11 in ai_hand:
            ai_hand[ai_hand.index(11)] = 1
            ai_sum = sum(ai_hand)
    
    while player_sum < 17:
        player_hand.append(random.choice(cards))
        player_sum = sum(player_hand)
        if player_sum > 21 and 11 in player_hand:
            player_hand[player_hand.index(11)] = 1
            player_sum = sum(player_hand)
    
    if player_sum > 21:
        player_stats[user.id]["games"]["blackjack"]["losses"] += 1
        player_stats[user.id]["losses"] += 1
        result = f"💔 Перебор! Ты проиграл!"
    elif ai_sum > 21:
        player_stats[user.id]["games"]["blackjack"]["wins"] += 1
        player_stats[user.id]["wins"] += 1
        result = f"🎉 У ИИ перебор! Ты выиграл!"
    elif player_sum > ai_sum:
        player_stats[user.id]["games"]["blackjack"]["wins"] += 1
        player_stats[user.id]["wins"] += 1
        result = f"🎉 Ты выиграл!"
    elif player_sum < ai_sum:
        player_stats[user.id]["games"]["blackjack"]["losses"] += 1
        player_stats[user.id]["losses"] += 1
        result = f"😢 Ты проиграл!"
    else:
        result = f"🤝 Ничья!"
    
    await update.message.reply_text(
        f"🃏 **Блэкджек 21**\n\n"
        f"Твои карты: {player_hand} = **{player_sum}**\n"
        f"Карты ИИ: {ai_hand} = **{ai_sum}**\n\n"
        f"{result}"
    )

# ============================================
# 📊 СТАТИСТИКА И РЕЙТИНГ
# ============================================
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_player(user.id, user.first_name)
    
    data = player_stats[user.id]
    text = f"📊 **Статистика {data['name']}**\n\n"
    text += f"🏆 Побед: {data['wins']}\n"
    text += f"💔 Поражений: {data['losses']}\n\n"
    text += "**По играм:**\n"
    
    games = {
        "roulette": "🔫 Русская рулетка",
        "guess": "🎲 Угадай число",
        "cards": "🃏 Карточная игра",
        "darts": "🎯 Дартс",
        "blackjack": "🃏 Блэкджек"
    }
    
    for key, name in games.items():
        w = data["games"][key]["wins"]
        l = data["games"][key]["losses"]
        if w > 0 or l > 0:
            text += f"{name}: {w} побед, {l} поражений\n"
    
    await update.message.reply_text(text)

async def show_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not player_stats:
        await update.message.reply_text("🏆 Пока нет игроков!")
        return
    
    sorted_players = sorted(player_stats.items(), key=lambda x: x[1]["wins"], reverse=True)
    
    text = "🏆 **Рейтинг игроков**\n\n"
    for i, (uid, data) in enumerate(sorted_players[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {data['name']} — {data['wins']} побед\n"
    
    await update.message.reply_text(text)

# ============================================
# 🤖 ОТВЕТ ИИ
# ============================================
async def handle_ai_response(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    chat_id = update.effective_chat.id
    
    history = chat_histories[chat_id]
    history.append({"role": "user", "content": text})
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
        history.pop()
    else:
        history.append({"role": "assistant", "content": reply_text})

    for i in range(0, len(reply_text), TELEGRAM_MSG_LIMIT):
        await update.message.reply_text(reply_text[i : i + TELEGRAM_MSG_LIMIT])

# ============================================
# ОБРАБОТКА СООБЩЕНИЙ
# ============================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    chat_type = update.effective_chat.type
    
    global BOT_USERNAME
    if BOT_USERNAME is None:
        bot_info = await context.bot.get_me()
        BOT_USERNAME = bot_info.username
    
    # Если в личке — сразу в ИИ-режим
    if chat_type == "private":
        await handle_ai_response(update, context, user_text)
        return
    
    # Если в группе — проверяем упоминание
    is_mentioned = False
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "mention":
                mention = user_text[entity.offset:entity.offset + entity.length]
                if mention == f"@{BOT_USERNAME}":
                    is_mentioned = True
                    break
            elif entity.type == "text_mention":
                if entity.user and entity.user.id == context.bot.id:
                    is_mentioned = True
                    break
    
    if is_mentioned:
        await handle_mention(update, context)

# ============================================
# ЗАПУСК
# ============================================
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🎮 БОТ ЗАПУЩЕН!")
    logger.info("📌 Работает через упоминания (как @celya)")
    logger.info("🤖 Режимы: @bot AI — ИИ-чат, @bot games — игры")
    app.run_polling()

if __name__ == "__main__":
    main()

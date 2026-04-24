import os
import logging
# Добавляем импорт HTTPXRequest
from telegram.request import HTTPXRequest 
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = "@easymarket_ge"
MOD_CHAT_ID = os.getenv("MOD_CHAT_ID", "178060329")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not found")

categories = [["👩 Женское"], ["📱 Электроника"], ["🚗 Авто"]]

CATEGORY_TARGETS = {
    "👩 Женское": {"chatId": CHAT_ID, "threadId": 17, "username": "easymarket_ge"},
    "📱 Электроника": {"chatId": CHAT_ID, "threadId": 9, "username": "easymarket_ge"},
    "🚗 Авто": {"chatId": CHAT_ID, "threadId": 8, "username": "easymarket_ge"},
}

ads = {}
pending_ads = {}

def category_keyboard():
    return ReplyKeyboardMarkup(categories, resize_keyboard=True, one_time_keyboard=True)

def back_keyboard():
    return ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    ads[user_id] = {"step": "category", "photos": []}
    await update.message.reply_text("Выберите категорию:", reply_markup=category_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text

    if user_id not in ads:
        return

    ad = ads[user_id]

    if ad["step"] == "category" and text in sum(categories, []):
        ad["category"] = text
        ad["step"] = "title"
        await update.message.reply_text("Введите заголовок:", reply_markup=back_keyboard())

    elif ad["step"] == "title":
        ad["title"] = text
        ad["step"] = "description"
        await update.message.reply_text("Введите описание:", reply_markup=back_keyboard())

    elif ad["step"] == "description":
        ad["description"] = text
        ad["step"] = "price"
        await update.message.reply_text("Введите цену:", reply_markup=back_keyboard())

    elif ad["step"] == "price":
        ad["price"] = text
        ad["contact"] = f"@{update.effective_user.username}" if update.effective_user.username else "Не указан"
        await preview_ad(update, context, ad, user_id)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if user_id not in ads:
        return

    ad = ads[user_id]

    if ad["step"] != "category" and len(ad["photos"]) < 5:
        photo = update.message.photo[-1]
        ad["photos"].append(photo.file_id)

async def preview_ad(update: Update, context: ContextTypes.DEFAULT_TYPE, ad, owner_id):
    caption = f"""
📦 {ad['category']}
📝 {ad['title']}
💬 {ad['description']}
💰 {ad['price']}
👤 {ad['contact']}
"""

    media = [InputMediaPhoto(p) for p in ad["photos"]]

    await context.bot.send_media_group(chat_id=owner_id, media=media)
    await context.bot.send_message(owner_id, "Отправить на модерацию?")

def main():
    # 1. Создаем объект запроса с увеличенными таймаутами (30 секунд вместо 5)
    # Это решит проблему с ConnectTimeout в Docker
    trequest = HTTPXRequest(
        connection_pool_size=20, 
        read_timeout=30.0, 
        write_timeout=30.0, 
        connect_timeout=30.0, 
        pool_timeout=30.0
    )

    # 2. Передаем настройки в builder через .request()
    app = Application.builder().token(BOT_TOKEN).request(trequest).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Bot started with custom timeouts")
    app.run_polling()

if __name__ == "__main__":
    main()

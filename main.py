import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.request import HTTPXRequest
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

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
pending_ads = {}  # mod_message_id -> ad


def category_keyboard():
    return ReplyKeyboardMarkup(categories, resize_keyboard=True, one_time_keyboard=True)


def back_keyboard():
    return ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)


def confirm_inline_keyboard(owner_id: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Отправить", callback_data=f"send:{owner_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"cancel:{owner_id}"),
            ]
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    ads[user_id] = {"step": "category", "photos": []}
    await update.message.reply_text("Выберите категорию:", reply_markup=category_keyboard())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text

    if text == "🔙 Назад":
        ads[user_id] = {"step": "category", "photos": []}
        await update.message.reply_text("Выберите категорию:", reply_markup=category_keyboard())
        return

    if user_id not in ads:
        await update.message.reply_text("Напишите /start чтобы начать.")
        return

    ad = ads[user_id]

    if ad["step"] == "category":
        if text in sum(categories, []):
            ad["category"] = text
            ad["step"] = "title"
            await update.message.reply_text("Введите заголовок:", reply_markup=back_keyboard())
        else:
            await update.message.reply_text("Выберите категорию кнопкой ниже:", reply_markup=category_keyboard())

    elif ad["step"] == "title":
        ad["title"] = text
        ad["step"] = "description"
        await update.message.reply_text("Введите описание:", reply_markup=back_keyboard())

    elif ad["step"] == "description":
        ad["description"] = text
        ad["step"] = "photos"
        await update.message.reply_text(
            "Пришлите до 5 фото, затем напишите «Готово» (или «Пропустить», если фото нет).",
            reply_markup=ReplyKeyboardMarkup([["Готово"], ["Пропустить"], ["🔙 Назад"]], resize_keyboard=True),
        )

    elif ad["step"] == "photos":
        if text.lower() in ("готово", "пропустить"):
            ad["step"] = "price"
            await update.message.reply_text("Введите цену:", reply_markup=back_keyboard())
        else:
            await update.message.reply_text("Пришлите фото или напишите «Готово» / «Пропустить».")

    elif ad["step"] == "price":
        ad["price"] = text
        ad["contact"] = (
            f"@{update.effective_user.username}" if update.effective_user.username else "Не указан"
        )
        ad["step"] = "confirm"
        await preview_ad(update, context, ad, user_id)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if user_id not in ads:
        return

    ad = ads[user_id]

    # принимаем фото только на шаге photos
    if ad["step"] == "photos" and len(ad["photos"]) < 5:
        photo = update.message.photo[-1]
        ad["photos"].append(photo.file_id)
        await update.message.reply_text(f"Фото добавлено ({len(ad['photos'])}/5).")


def build_caption(ad: dict) -> str:
    return (
        f"📦 {ad['category']}\n"
        f"📝 {ad['title']}\n"
        f"💬 {ad['description']}\n"
        f"💰 {ad['price']}\n"
        f"👤 {ad['contact']}"
    )


async def send_photos(context: ContextTypes.DEFAULT_TYPE, chat_id, photos, caption=None, **kwargs):
    """Корректно отправляет 0/1/2+ фото."""
    if not photos:
        if caption:
            await context.bot.send_message(chat_id=chat_id, text=caption, **kwargs)
        return
    if len(photos) == 1:
        await context.bot.send_photo(chat_id=chat_id, photo=photos[0], caption=caption, **kwargs)
        return
    media = [InputMediaPhoto(p, caption=caption if i == 0 else None) for i, p in enumerate(photos)]
    await context.bot.send_media_group(chat_id=chat_id, media=media, **kwargs)


async def preview_ad(update: Update, context: ContextTypes.DEFAULT_TYPE, ad, owner_id):
    caption = build_caption(ad)
    try:
        await send_photos(context, owner_id, ad["photos"], caption=caption)
    except Exception as e:
        logger.exception("Failed to send preview photos: %s", e)
        await context.bot.send_message(owner_id, caption)

    await context.bot.send_message(
        owner_id,
        "Отправить на модерацию?",
        reply_markup=confirm_inline_keyboard(owner_id),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("send:"):
        owner_id = data.split(":", 1)[1]
        ad = ads.get(owner_id)
        if not ad:
            await query.edit_message_text("Сессия устарела. Начните заново: /start")
            return
        # Отправляем модератору
        try:
            caption = build_caption(ad)
            await send_photos(context, MOD_CHAT_ID, ad["photos"], caption=caption)
            await context.bot.send_message(MOD_CHAT_ID, f"От пользователя id={owner_id}")
            await query.edit_message_text("✅ Отправлено на модерацию.")
        except Exception as e:
            logger.exception("Failed to send to moderator: %s", e)
            await query.edit_message_text(f"❌ Не удалось отправить модератору: {e}")
        finally:
            ads.pop(owner_id, None)

    elif data.startswith("cancel:"):
        owner_id = data.split(":", 1)[1]
        ads.pop(owner_id, None)
        await query.edit_message_text("Отменено. Напишите /start чтобы начать заново.")


# --- Health server для платформ вроде Amvera/RelaxDev, которым нужен открытый порт ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args, **kwargs):
        return  # подавляем стандартный лог


def run_health_server():
    port = int(os.getenv("PORT", "80"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        logger.info("Health server listening on 0.0.0.0:%s", port)
        server.serve_forever()
    except Exception as e:
        logger.exception("Health server failed: %s", e)


def main():
    # Запускаем health-сервер в фоне — чтобы платформа видела открытый порт
    threading.Thread(target=run_health_server, daemon=True).start()

    # Увеличенные таймауты — решают проблемы с ConnectTimeout в контейнерах
    trequest = HTTPXRequest(
        connection_pool_size=20,
        read_timeout=30.0,
        write_timeout=30.0,
        connect_timeout=30.0,
        pool_timeout=30.0,
    )

    app = Application.builder().token(BOT_TOKEN).request(trequest).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Bot started with custom timeouts")
    # drop_pending_updates=True — чтобы при рестарте не подхватывать старую очередь
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

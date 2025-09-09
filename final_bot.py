import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
from rubpy import BotClient
from eitaa import Eitaa

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    EITAA_BOT_TOKEN = os.environ.get("EITAA_BOT_TOKEN")
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
    PYTHONUNBUFFERED = os.environ.get("PYTHONUNBUFFERED")
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی تنظیم نشده یا فرمت آن اشتباه است.")
    exit()

PORT = int(os.environ.get("PORT", 10000))
IRAN_TIMEZONE = pytz.timezone('Asia/Tehran')

# ===============================================================
# بخش اصلی کد
# ===============================================================
rubika_bot: BotClient | None = None
eitaa_bot: Eitaa | None = None
telegram_app: Application | None = None
routing_map = {}
source_channel_ids = []
message_map = {}
stats = {}

# ... (تمام توابع دیگر شما تا main بدون تغییر باقی می مانند)

def main():
    global routing_map, source_channel_ids
    # *** پردازش نقشه کانال ها اصلاح شد ***
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            if pair.count(':') == 2: # مطمئن می شویم که فرمت صحیح است
                tg_id, rb_id, et_id = pair.split(':', 2)
                routing_map[int(tg_id.strip())] = {"rubika": rb_id.strip(), "eitaa": et_id.strip()}
        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است یا فرمت آن اشتباه است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش متغیر محیطی CHANNEL_MAP: {e}")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    admin_filter = filters.User(user_id=TELEGRAM_ADMIN_IDS)
    
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=source_channel_ids) & filters.UpdateType.CHANNEL_POST,
        telegram_channel_handler
    ))
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=source_channel_ids) & filters.UpdateType.EDITED_CHANNEL_POST,
        telegram_edited_channel_handler
    ))
    
    app.add_handler(CommandHandler("admin", admin_panel, filters=admin_filter))
    # ... (بقیه هندلرهای ادمین)
    
    print("==================================================")
    print("ربات فورواردر چند پلتفرمی (نسخه اصلاح شده) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

# (لطفاً بقیه توابع خود را که در اینجا برای اختصار حذف شده، در کد نهایی قرار دهید)
# ... توابع post_init, post_shutdown, telegram_channel_handler و ...

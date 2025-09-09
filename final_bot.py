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

# --- توابع مدیریت فایل و آمار (بدون تغییر) ---
def get_default_stats():
    return {"total_forwarded": 0, "by_type": {}, "errors": 0, "last_activity_time": None}
def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data
def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

async def post_init(application: Application):
    global rubika_bot, eitaa_bot, message_map, stats, telegram_app
    telegram_app = application
    
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")

    print("در حال ساخت و فعال سازی کلاینت ایتا...")
    eitaa_bot = Eitaa(EITAA_BOT_TOKEN)
    print("کلاینت ایتا با موفقیت فعال شد.")
    
    message_map = load_data_from_file('message_map.json', {})
    stats = load_data_from_file('stats.json', get_default_stats())
    
    for admin_id in TELEGRAM_ADMIN_IDS:
        await telegram_app.bot.send_message(chat_id=admin_id, text="✅ ربات چند پلتفرمی با موفقیت آنلاین شد.")

async def post_shutdown(application: Application):
    if rubika_bot:
        await rubika_bot.close()

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats, telegram_app
    message = update.channel_post
    if not (message and rubika_bot and eitaa_bot): return

    source_id = message.chat_id
    destination_ids = routing_map.get(source_id)
    if not destination_ids: return

    rubika_dest = destination_ids.get("rubika")
    eitaa_dest = destination_ids.get("eitaa")

    print(f"\nپیام جدید از تلگرام ({source_id}) -> ارسال به روبیکا ({rubika_dest}) و ایتا ({eitaa_dest})")
    
    try:
        caption = message.caption or ""
        sent_rubika_message, sent_eitaa_message = None, None

        if message.text:
            if rubika_dest: sent_rubika_message = await rubika_bot.send_message(rubika_dest, message.text)
            if eitaa_dest: sent_eitaa_message = eitaa_bot.send_message(eitaa_dest, message.text)

        elif message.photo:
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            if rubika_dest: sent_rubika_message = await rubika_bot.send_file(rubika_dest, file=str(file_path), text=caption, type='Image')
            if eitaa_dest: sent_eitaa_message = eitaa_bot.send_file(eitaa_dest, file=str(file_path), caption=caption)
            os.remove(file_path)

        # ... (منطق مشابه برای ویدیو و انواع دیگر فایل)
        
        print("--> فوروارد با موفقیت انجام شد.")
        
        # ... (بخش آمار و ثبت شناسه ها)

    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
        # ... (منطق ارسال خطا به ادمین)
        
    print(f"==============================================\n")


def main():
    global routing_map, source_channel_ids
    # ... (پردازش نقشه کانال ها بدون تغییر)
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            if pair.count(':') == 2:
                tg_id, rb_id, et_id = pair.split(':')
                routing_map[int(tg_id.strip())] = {"rubika": rb_id.strip(), "eitaa": et_id.strip()}
        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش متغیر محیطی CHANNEL_MAP: {e}")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    # ... (تمام هندلرهای شما بدون تغییر باقی می مانند)
    
    print("==================================================")
    print("ربات فورواردر چند پلتفرمی آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

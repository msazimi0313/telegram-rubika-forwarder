import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
from rubpy import BotClient

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
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
telegram_app: Application | None = None
routing_map = {}
source_channel_ids = []
message_map = {}
stats = {}

# ... (توابع get_default_stats, load_data, save_data بدون تغییر)

async def post_init(application: Application):
    global rubika_bot, message_map, stats, telegram_app
    telegram_app = application
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")
    message_map = load_data_from_file('message_map.json', {})
    stats = load_data_from_file('stats.json', get_default_stats())
    for admin_id in TELEGRAM_ADMIN_IDS:
        try:
            await telegram_app.bot.send_message(chat_id=admin_id, text="✅ ربات با موفقیت آنلاین و راه‌اندازی شد.")
        except Exception as e:
            print(f"خطا در ارسال پیام به ادمین {admin_id}: {e}")

async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا با موفقیت متوقف شد.")


# *** تابع جدید برای انجام کار اصلی در پس زمینه ***
async def forward_message_task(source_id, message):
    global stats, telegram_app, message_map
    
    destination_ids = routing_map.get(source_id)
    if not destination_ids: return

    rubika_dest = destination_ids.get("rubika")
    eitaa_dest = destination_ids.get("eitaa")

    print(f"پردازش پیام از تلگرام ({source_id}) -> ارسال به روبیکا ({rubika_dest}) و ایتا ({eitaa_dest})")
    
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

        print("--> فوروارد با موفقیت انجام شد.")
        # ... (بخش آمار و ثبت شناسه ها)
    
    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
        error_text = f"❌ خطا در فوروارد از {source_id}:\n\n`{e}`"
        for admin_id in TELEGRAM_ADMIN_IDS:
            await telegram_app.bot.send_message(chat_id=admin_id, text=error_text)
    print(f"==============================================\n")


# *** هندلر اصلی که فقط وظیفه را در پس زمینه اجرا می کند ***
async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post: return
    source_id = update.channel_post.chat_id
    print(f"\n==============================================")
    print(f"پیام جدید از کانال تلگرام ({source_id}) دریافت شد. اجرای فوروارد در پس زمینه...")
    # اجرای کار اصلی در پس زمینه
    asyncio.create_task(forward_message_task(source_id, update.channel_post))


# ... (بقیه توابع شما بدون تغییر باقی می مانند)

def main():
    global routing_map, source_channel_ids
    # ... (پردازش نقشه کانال ها)
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            if pair.count(':') >= 2: # حداقل باید ۳ بخش داشته باشد
                tg_id, rb_id, et_id = pair.split(':', 2)
                routing_map[int(tg_id.strip())] = {"rubika": rb_id.strip(), "eitaa": et_id.strip()}
        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش متغیر محیطی CHANNEL_MAP: {e}")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    # اضافه کردن فقط یک هندلر اصلی
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=source_channel_ids) & filters.UpdateType.CHANNEL_POST,
        telegram_channel_handler
    ))
    
    # ... (اضافه کردن هندلرهای ادمین)
    
    print("==================================================")
    print("ربات فورواردر (با پردازش پس زمینه) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

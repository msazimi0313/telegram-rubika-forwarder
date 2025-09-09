import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
from rubpy import BotClient
from eitaabot import Client as EitaaClient # <-- اضافه شدن کتابخانه ایتا
import aiohttp # <-- اضافه شدن کتابخانه برای ارسال فایل به ایتا

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    EITAA_BOT_TOKEN = os.environ.get("EITAA_BOT_TOKEN") # <-- توکن جدید ایتا
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
eitaa_bot: EitaaClient | None = None # <-- کلاینت جدید ایتا
telegram_app: Application | None = None
routing_map = {}
source_channel_ids = []
message_map = {}
stats = {}

# ... (توابع get_default_stats, load_data_from_file, save_data_to_file بدون تغییر)

async def post_init(application: Application):
    global rubika_bot, eitaa_bot, message_map, stats, telegram_app
    telegram_app = application
    
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")

    print("در حال ساخت و فعال سازی کلاینت ایتا...")
    eitaa_bot = EitaaClient(EITAA_BOT_TOKEN)
    print("کلاینت ایتا با موفقیت فعال شد.")
    
    # ... (بقیه تابع post_init بدون تغییر)
    
async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
    # Eitaa client doesn't have a close method in this library

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats, telegram_app
    message = update.channel_post
    if not (message and rubika_bot and eitaa_bot): return

    source_id = message.chat_id
    # پیدا کردن مقصدهای روبیکا و ایتا
    destination_ids = routing_map.get(source_id)
    if not destination_ids: return

    rubika_dest = destination_ids.get("rubika")
    eitaa_dest = destination_ids.get("eitaa")

    print(f"\n==============================================")
    print(f"پیام جدید از تلگرام ({source_id}) -> ارسال به روبیکا ({rubika_dest}) و ایتا ({eitaa_dest})")
    
    try:
        caption = message.caption or ""
        sent_rubika_message = None
        sent_eitaa_message = None # برای ثبت شناسه پیام ایتا

        if message.text:
            # ارسال به روبیکا
            if rubika_dest:
                sent_rubika_message = await rubika_bot.send_message(rubika_dest, message.text)
                print("--> پیام متنی با موفقیت به کانال روبیکا ارسال شد.")
            # ارسال به ایتا
            if eitaa_dest:
                sent_eitaa_message = await eitaa_bot.send_message(eitaa_dest, message.text)
                print("--> پیام متنی با موفقیت به کانال ایتا ارسال شد.")

        elif message.photo:
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            
            # ارسال به روبیکا
            if rubika_dest:
                sent_rubika_message = await rubika_bot.send_file(rubika_dest, file=str(file_path), text=caption, type='Image')
                print("--> عکس با موفقیت به کانال روبیکا ارسال شد.")
            
            # ارسال به ایتا (با aiohttp برای آپلود فایل)
            if eitaa_dest:
                async with aiohttp.ClientSession() as session:
                    with open(file_path, 'rb') as f:
                        form_data = aiohttp.FormData()
                        form_data.add_field('chat_id', eitaa_dest)
                        form_data.add_field('caption', caption)
                        form_data.add_field('file', f, filename=os.path.basename(file_path))
                        
                        async with session.post(f"https://eitaayar.ir/api/{EITAA_BOT_TOKEN}/sendFile", data=form_data) as response:
                            if response.status == 200:
                                print("--> عکس با موفقیت به کانال ایتا ارسال شد.")
                                sent_eitaa_message = (await response.json()).get("result")
                            else:
                                print(f"!! خطا در ارسال عکس به ایتا: {await response.text()}")
            
            os.remove(file_path)

        # ... (منطق مشابه برای ویدیو و انواع دیگر فایل باید اضافه شود)

        # آپدیت آمار و شناسه ها
        if (sent_rubika_message or sent_eitaa_message):
            # ... (بخش آمار و ثبت شناسه ها نیاز به بازنویسی دارد تا هر دو مقصد را مدیریت کند)
            stats["total_forwarded"] += 1
            # ...
            save_data_to_file('stats.json', stats)

    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
        # ... (منطق ارسال خطا به ادمین)
        
    print(f"==============================================\n")


def main():
    global routing_map, source_channel_ids
    # پردازش نقشه کانال های جدید
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

    # ... (بقیه کد main بدون تغییر)

if __name__ == '__main__':
    main()

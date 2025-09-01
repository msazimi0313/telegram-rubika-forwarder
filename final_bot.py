import asyncio
import os
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes
from rubpy import BotClient

# ===============================================================
# بخش تنظیمات (بدون تغییر)
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_SOURCE_CHANNEL_ID = int(os.environ.get("TELEGRAM_SOURCE_CHANNEL_ID"))
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    RUBIKA_DESTINATION_CHANNEL_ID = os.environ.get("RUBIKA_DESTINATION_CHANNEL_ID")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
    PYTHONUNBUFFERED = os.environ.get("PYTHONUNBUFFERED")
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی تنظیم نشده یا فرمت آن اشتباه است.")
    exit()

PORT = int(os.environ.get("PORT", 10000))

# ===============================================================
# بخش اصلی کد (بازنویسی شده)
# ===============================================================

# 1. ساخت کلاینت روبیکا
rubika_bot = BotClient(RUBIKA_BOT_TOKEN)

# 2. ساخت اپلیکیشن تلگرام (بدون اجرای آن)
telegram_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

# 3. تعریف "دفترچه یادداشت" برای نگهداری شناسه پیام ها
message_map = {}

# --- تعریف توابع رویداد برای ربات روبیکا ---

@rubika_bot.on_start()
async def on_startup(client: BotClient):
    """این تابع یک بار در زمان آنلاین شدن ربات روبیکا اجرا می شود"""
    print("کلاینت روبیکا با موفقیت فعال شد.")
    print("در حال راه اندازی شنونده تلگرام در حالت وبهوک...")
    
    # اجرای شنونده تلگرام در پس زمینه
    # ما دیگر منتظر پایان اجرای وبهوک نمی مانیم
    asyncio.create_task(telegram_app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    ))
    print("==================================================")
    print("ربات فورواردر به طور کامل آنلاین و آماده به کار است.")
    print("==================================================")

@rubika_bot.on_shutdown()
async def on_shutdown(client: BotClient):
    """این تابع در زمان خاموش شدن ربات روبیکا اجرا می شود"""
    print("در حال متوقف کردن شنونده تلگرام...")
    await telegram_app.shutdown()
    print("شنونده تلگرام با موفقیت متوقف شد.")
    print("کلاینت روبیکا با موفقیت متوقف شد.")


# --- تعریف توابع پردازش پیام تلگرام (بدون تغییر در منطق) ---

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message: return

    print(f"\n==============================================")
    print(f"یک پیام جدید از کانال تلگرام دریافت شد.")
    try:
        caption = message.caption or ""
        sent_rubika_message = None
        if message.text:
            sent_rubika_message = await rubika_bot.send_message(RUBIKA_DESTINATION_CHANNEL_ID, message.text)
            print("--> پیام متنی با موفقیت به کانال روبیکا ارسال شد.")
        elif message.photo:
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            sent_rubika_message = await rubika_bot.send_file(RUBIKA_DESTINATION_CHANNEL_ID, file=str(file_path), text=caption, type='Image')
            print("--> عکس با موفقیت به کانال روبیکا ارسال شد.")
            os.remove(file_path)

        if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
            telegram_id = message.message_id
            rubika_id = sent_rubika_message.message_id
            message_map[telegram_id] = rubika_id
            print(f"  -> شناسه ها ثبت شد: تلگرام({telegram_id}) -> روبیکا({rubika_id})")
        else:
            print("--> پیام از نوع پشتیبانی نشده و نادیده گرفته شد.")
    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
    print(f"==============================================\n")

async def telegram_edited_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edited_message = update.edited_channel_post
    if not edited_message: return
    print(f"\n==============================================")
    print(f"یک پیام ویرایش شده از تلگرام دریافت شد.")
    try:
        telegram_id = edited_message.message_id
        if telegram_id in message_map:
            rubika_id = message_map[telegram_id]
            new_content = edited_message.text or edited_message.caption or ""
            await rubika_bot.edit_message_text(RUBIKA_DESTINATION_CHANNEL_ID, rubika_id, new_content)
            print(f"--> پیام ({rubika_id}) در روبیکا با موفقیت ویرایش شد.")
        else:
            print("--> شناسه پیام ویرایش شده در دفترچه یافت نشد.")
    except Exception as e:
        print(f"!! یک خطا در هنگام ویرایش پیام رخ داد: {e}")
    print(f"==============================================\n")


# --- بخش نهایی: اضافه کردن شنونده ها و اجرای ربات ---

def main():
    # اضافه کردن شنونده ها به اپلیکیشن تلگرام
    telegram_app.add_handler(MessageHandler(
        filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.CHANNEL_POST,
        telegram_channel_handler
    ))
    telegram_app.add_handler(MessageHandler(
        filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.EDITED_CHANNEL_POST,
        telegram_edited_channel_handler
    ))
    
    # اجرای ربات روبیکا (که به صورت خودکار ربات تلگرام را هم راه اندازی می کند)
    rubika_bot.run()

if __name__ == '__main__':
    main()

import asyncio
import os
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes
from rubpy import BotClient

# ... (بخش تنظیمات بدون تغییر)
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_SOURCE_CHANNEL_ID = int(os.environ.get("TELEGRAM_SOURCE_CHANNEL_ID"))
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    RUBIKA_DESTINATION_CHAT_ID = os.environ.get("RUBIKA_DESTINATION_CHAT_ID")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی تنظیم نشده یا فرمت آن اشتباه است.")
    exit()

PORT = int(os.environ.get("PORT", 8443))
# ... (کدهای post_init و post_shutdown بدون تغییر)

rubika_bot: BotClient | None = None

async def post_init(application: Application):
    global rubika_bot
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")

async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا با موفقیت متوقف شد.")

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not (message and rubika_bot):
        return

    print(f"\n==============================================")
    print(f"یک پیام جدید از کانال تلگرام دریافت شد.")
    
    # این کد فقط به پیام های ویدیویی واکنش نشان می دهد
    if message.video:
        try:
            print("مرحله ۱: پیام ویدیویی شناسایی شد.")
            caption = message.caption or ""
            print("مرحله ۲: کپشن استخراج شد.")

            file = await message.video.get_file()
            print("مرحله ۳: آبجکت فایل از تلگرام دریافت شد.")

            file_path = await file.download_to_drive()
            print(f"مرحله ۴: ویدیو در مسیر '{file_path}' دانلود شد.")

            await rubika_bot.send_file(
                RUBIKA_DESTINATION_CHAT_ID,
                file=str(file_path),
                text=caption,
                type='Video'
            )
            print("مرحله ۵: دستور ارسال ویدیو به روبیکا اجرا شد.")

            os.remove(file_path)
            print("مرحله ۶: فایل موقت پاک شد.")
            print("--> فرآیند ویدیو با موفقیت کامل انجام شد.")

        except Exception as e:
            print(f"!! یک خطا در هنگام پردازش ویدیو رخ داد: {e}")
    else:
        print("--> پیام از نوع ویدیو نبود و نادیده گرفته شد.")
        
    print(f"==============================================\n")


def main():
    # ... (بخش main بدون تغییر)
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID), telegram_channel_handler))
    print("==================================================")
    print("ربات در حالت تست ویدیو آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

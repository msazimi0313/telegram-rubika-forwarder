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
    RUBIKA_DESTINATION_CHAT_ID = os.environ.get("RUBIKA_DESTINATION_CHAT_ID")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی تنظیم نشده یا فرمت آن اشتباه است.")
    exit()

PORT = int(os.environ.get("PORT", 8443))

# ===============================================================
# بخش اصلی کد
# ===============================================================

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
    try:
        caption = message.caption or ""

        # ارسال پیام متنی
        if message.text:
            await rubika_bot.send_message(RUBIKA_DESTINATION_CHAT_ID, message.text)
            print("--> پیام متنی با موفقیت به روبیکا ارسال شد.")

        # ارسال عکس
        elif message.photo:
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            await rubika_bot.send_file(RUBIKA_DESTINATION_CHAT_ID, file=str(file_path), text=caption, type='Image')
            print("--> عکس با موفقیت به روبیکا ارسال شد.")
            os.remove(file_path)
            
        # ارسال ویدیو (با راه‌حل نهایی و ارسال تامبنیل)
        elif message.video:
            print("پیام حاوی ویدیو شناسایی شد.")
            video = message.video
            thumbnail_path = None
            
            # 1. دانلود تامبنیل ویدیو (اگر وجود داشت)
            if video.thumbnail:
                print("تامبنیل پیدا شد. در حال دانلود تامبنیل...")
                thumb_file = await video.thumbnail.get_file()
                thumbnail_path = await thumb_file.download_to_drive()
                print(f"تامبنیل در مسیر '{thumbnail_path}' دانلود شد.")
            
            # 2. دانلود خود ویدیو
            file = await video.get_file()
            file_path = await file.download_to_drive()
            print(f"ویدیو در مسیر '{file_path}' دانلود شد.")
            
            # 3. ارسال ویدیو به همراه تمام جزئیات مورد نیاز
            await rubika_bot.send_file(
                RUBIKA_DESTINATION_CHAT_ID,
                file=str(file_path),
                text=caption,
                type='Video',
                thumbnail=str(thumbnail_path) if thumbnail_path else None,
                duration=video.duration,
                width=video.width,
                height=video.height
            )
            print("--> ویدیو (به همراه تامبنیل و کپشن) با موفقیت به روبیکا ارسال شد.")
            
            # 4. پاک کردن فایل های موقت
            os.remove(file_path)
            if thumbnail_path:
                os.remove(thumbnail_path)
            print("فایل های موقت پاک شدند.")

    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
    print(f"==============================================\n")


def main():
    # ... (بخش main بدون تغییر)
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID), telegram_channel_handler))
    print("==================================================")
    print("ربات فورواردر نهایی (نسخه کامل) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

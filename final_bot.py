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
            await rubika_bot.send_message(RUBIKA_DESTINATION_CHANNEL_ID, message.text)
            print("--> پیام متنی با موفقیت به کانال روبیکا ارسال شد.")
            
        # ارسال عکس
        elif message.photo:
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            await rubika_bot.send_file(RUBIKA_DESTINATION_CHANNEL_ID, file=str(file_path), text=caption, type='Image')
            print("--> عکس با موفقیت به کانال روبیکا ارسال شد.")
            os.remove(file_path)
            
        # ارسال ویدیو
        elif message.video:
            file = await message.video.get_file()
            file_path = await file.download_to_drive()
            await rubika_bot.send_file(RUBIKA_DESTINATION_CHANNEL_ID, file=str(file_path), text=caption, type='Video')
            print("--> ویدیو با موفقیت به کانال روبیکا ارسال شد.")
            os.remove(file_path)
        
        # *** بلوک جدید برای موسیقی/فایل صوتی ***
        elif message.audio:
            print("پیام حاوی موسیقی/صوت شناسایی شد.")
            audio = message.audio
            # ساخت یک کپشن بهتر با اطلاعات فایل صوتی
            full_caption = ""
            if audio.performer and audio.title:
                full_caption = f"🎵 {audio.performer} - {audio.title}\n\n"
            full_caption += caption
            
            file = await audio.get_file()
            file_path = await file.download_to_drive()
            print(f"فایل صوتی در '{file_path}' دانلود شد.")
            
            # فایل صوتی را به عنوان یک فایل عمومی ارسال می کنیم
            await rubika_bot.send_file(RUBIKA_DESTINATION_CHANNEL_ID, file=str(file_path), text=full_caption)
            print("--> فایل صوتی با موفقیت به کانال روبیکا ارسال شد.")
            os.remove(file_path)
            
        # *** بلوک جدید برای داکیومنت/فایل عمومی ***
        elif message.document:
            print("پیام حاوی داکیومنت/فایل شناسایی شد.")
            file = await message.document.get_file()
            file_path = await file.download_to_drive()
            print(f"فایل در '{file_path}' دانلود شد.")
            
            await rubika_bot.send_file(RUBIKA_DESTINATION_CHANNEL_ID, file=str(file_path), text=caption)
            print("--> داکیومنت با موفقیت به کانال روبیکا ارسال شد.")
            os.remove(file_path)

        # *** بلوک جدید برای نظرسنجی ***
        elif message.poll:
            print("پیام حاوی نظرسنجی شناسایی شد.")
            poll = message.poll
            question = poll.question
            options = [option.text for option in poll.options]
            
            # استفاده از متد send_poll کتابخانه روبپای
            await rubika_bot.send_poll(RUBIKA_DESTINATION_CHANNEL_ID, question=question, options=options)
            print("--> نظرسنجی با موفقیت به کانال روبیکا ارسال شد.")
            
        else:
            print("--> پیام از نوع پشتیبانی نشده (مانند استیکر و...) و نادیده گرفته شد.")
            
    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
    print(f"==============================================\n")


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID), telegram_channel_handler))
    print("==================================================")
    print("ربات فورواردر کامل آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

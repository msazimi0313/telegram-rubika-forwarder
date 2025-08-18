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
# ...

rubika_bot: BotClient | None = None

async def post_init(application: Application):
    global rubika_bot
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")
    
    # *** تغییر مهم: ما دیگر وبهوک را اینجا تنظیم نمی کنیم ***
    # تابع run_webhook خودش این کار را در زمان صحیح انجام می دهد

# ... (تابع post_shutdown و telegram_channel_handler بدون تغییر باقی می ماند)
async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا با موفقیت متوقف شد.")

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not (message and rubika_bot):
        return
    print(f"\nیک پیام جدید از کانال تلگرام دریافت شد.")
    try:
        if message.text:
            await rubika_bot.send_message(RUBIKA_DESTINATION_CHAT_ID, message.text)
            print("--> پیام متنی با موفقیت به روبیکا ارسال شد.")
        elif message.photo:
            caption = message.caption or ""
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            await rubika_bot.send_file(RUBIKA_DESTINATION_CHAT_ID, file=str(file_path), text=caption, type='Image')
            print("--> عکس با موفقیت به روبیکا ارسال شد.")
            os.remove(file_path)
    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID), telegram_channel_handler))
    
    print("==================================================")
    print("ربات فورواردر در حالت وبهوک آماده اجرا است...")
    print("==================================================")
    
    # *** تغییر نهایی و کلیدی ***
    # ما آدرس وبهوک را مستقیماً به run_webhook می دهیم
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

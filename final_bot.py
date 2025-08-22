import asyncio
import os
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes
from rubpy import BotClient
from moviepy.editor import VideoFileClip  # کتابخانه جدید را وارد می کنیم

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
    try:
        caption = message.caption or ""
        # ... (بخش ارسال متن و عکس بدون تغییر)
        if message.text:
            await rubika_bot.send_message(RUBIKA_DESTINATION_CHAT_ID, message.text)
            print("--> پیام متنی با موفقیت به روبیکا ارسال شد.")
        elif message.photo:
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            await rubika_bot.send_file(RUBIKA_DESTINATION_CHAT_ID, file=str(file_path), text=caption, type='Image')
            print("--> عکس با موفقیت به روبیکا ارسال شد.")
            os.remove(file_path)
            
        # ارسال ویدیو (با قابلیت تغییر اندازه خودکار)
        elif message.video:
            print("پیام حاوی ویدیو شناسایی شد.")
            video = message.video
            
            # 1. دانلود ویدیو اصلی
            original_file = await video.get_file()
            original_path = await original_file.download_to_drive()
            print(f"ویدیو اصلی در '{original_path}' دانلود شد.")

            # 2. پردازش و تغییر اندازه با moviepy
            clip = VideoFileClip(str(original_path))
            width, height = clip.size
            max_size = 720
            output_path = str(original_path) # به صورت پیش فرض فایل خروجی همان فایل ورودی است

            if width > max_size or height > max_size:
                print(f"ابعاد ویدیو ({width}x{height}) بزرگتر از حد مجاز است. در حال تغییر اندازه...")
                scale_factor = min(max_size / width, max_size / height)
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)
                
                output_path_resized = "resized_" + os.path.basename(original_path)
                
                resized_clip = clip.resize(newsize=(new_width, new_height))
                resized_clip.write_videofile(output_path_resized, codec='libx264', logger=None)
                output_path = output_path_resized # فایل خروجی ما، فایل تغییر اندازه داده شده است
                print(f"ویدیو با موفقیت به ابعاد {new_width}x{new_height} تغییر اندازه داد.")
            else:
                print("ابعاد ویدیو مناسب است. نیازی به تغییر اندازه نیست.")

            # 3. ارسال فایل نهایی به روبیکا
            await rubika_bot.send_file(
                RUBIKA_DESTINATION_CHAT_ID,
                file=output_path,
                text=caption,
                type='Video'
            )
            print("--> ویدیو با موفقیت به روبیکا ارسال شد.")
            
            # 4. پاک کردن فایل های موقت
            clip.close()
            os.remove(original_path)
            if output_path != str(original_path):
                os.remove(output_path)
            print("فایل های موقت پاک شدند.")

    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
    print(f"==============================================\n")


def main():
    # ... (بخش main بدون تغییر)
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID), telegram_channel_handler))
    print("==================================================")
    print("ربات فورواردر نهایی (با پردازش ویدیو) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

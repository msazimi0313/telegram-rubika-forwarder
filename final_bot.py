import asyncio
import os
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes
from rubpy import BotClient

# ===============================================================
# بخش تنظیمات
# ===============================================================
TELEGRAM_BOT_TOKEN = "8286659809:AAHJBWJ0ARkpiKhV7zpHRw_qLVwq3pU4F8I"
TELEGRAM_SOURCE_CHANNEL_ID = -1001470415555
RUBIKA_BOT_TOKEN = "CCCDH0BPUUWJLSELQYFZHKVSBMFGLTGZYGFBRXKCGANQJEUPKKCVZKBVZKDPHPSG"
RUBIKA_DESTINATION_CHAT_ID = "b0C5W4U0Fy8094b58c46cceb2d103b1a"

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
        # ارسال پیام متنی
        if message.text:
            print(f"پیام متنی شناسایی شد: '{message.text}'")
            await rubika_bot.send_message(RUBIKA_DESTINATION_CHAT_ID, message.text)
            print("--> پیام متنی با موفقیت به PV شما در روبیکا ارسال شد.")

        # ارسال عکس (با راه‌حل نهایی)
        elif message.photo:
            print("پیام حاوی عکس شناسایی شد.")
            caption = message.caption or ""
            file = await message.photo[-1].get_file()
            file_path = await file.download_to_drive()
            print(f"عکس در مسیر موقت '{file_path}' دانلود شد.")
            
            # *** تغییر نهایی اینجاست ***
            await rubika_bot.send_file(
                RUBIKA_DESTINATION_CHAT_ID,
                file=str(file_path),
                text=caption,
                type='Image'  # با این پارامتر، فایل به صورت عکس نمایش داده می شود
            )
            print("--> عکس به صورت تصویر (به همراه کپشن) با موفقیت به PV شما در روبیکا ارسال شد.")

            os.remove(file_path)
            print("فایل موقت پاک شد.")

    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
    print(f"==============================================\n")


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID), telegram_channel_handler))
    print("==================================================")
    print("ربات فورواردر نهایی (ارسال به PV) آنلاین شد...")
    print("==================================================")
    app.run_polling()


if __name__ == '__main__':
    main()
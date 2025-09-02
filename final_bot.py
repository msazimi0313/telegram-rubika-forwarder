import asyncio
import os
import json
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes
from rubpy import BotClient

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_SOURCE_CHANNEL_ID = int(os.environ.get("TELEGRAM_SOURCE_CHANNEL_ID"))
    
    # خواندن لیست ادمین ها از متغیر محیطی
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    RUBIKA_DESTINATION_CHANNEL_ID = os.environ.get("RUBIKA_DESTINATION_CHANNEL_ID")
    
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
    PYTHONUNBUFFERED = os.environ.get("PYTHONUNBUFFERED")
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی (شامل TELEGRAM_ADMIN_ID) تنظیم نشده یا فرمت آن اشتباه است.")
    exit()

PORT = int(os.environ.get("PORT", 10000))

# ===============================================================
# بخش اصلی کد
# ===============================================================

rubika_bot: BotClient | None = None
message_map = {}
stats = {"forwarded_messages": 0}

def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data_to_file(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

async def post_init(application: Application):
    global rubika_bot, message_map, stats
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")
    
    message_map = load_data_from_file('message_map.json', {})
    stats = load_data_from_file('stats.json', {"forwarded_messages": 0})
    print("اطلاعات قبلی (شناسه ها و آمار) با موفقیت بارگذاری شد.")

async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا با موفقیت متوقف شد.")

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats
    message = update.channel_post
    if not (message and rubika_bot): return

    print(f"\n==============================================")
    print(f"یک پیام جدید از کانال تلگرام دریافت شد.")
    try:
        caption = message.caption or ""
        sent_rubika_message = None

        if message.text:
            sent_rubika_message = await rubika_bot.send_message(RUBIKA_DESTINATION_CHANNEL_ID, message.text)
            print("--> پیام متنی با موفقیت به کانال روبیکا ارسال شد.")
        elif message.photo or message.video or message.document:
            file_to_process = message.photo[-1] if message.photo else (message.video or message.document)
            file_type = 'Image' if message.photo else ('Video' if message.video else 'File')
            
            tg_file = await file_to_process.get_file()
            file_path = await tg_file.download_to_drive()
            
            sent_rubika_message = await rubika_bot.send_file(
                RUBIKA_DESTINATION_CHANNEL_ID,
                file=str(file_path),
                text=caption,
                type=file_type if file_type != 'File' else None
            )
            print(f"--> فایل از نوع '{file_type}' با موفقیت به کانال روبیکا ارسال شد.")
            os.remove(file_path)

        if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
            telegram_id = message.message_id
            rubika_id = sent_rubika_message.message_id
            message_map[str(telegram_id)] = rubika_id
            save_data_to_file('message_map.json', message_map)
            print(f"  -> شناسه ها ثبت و ذخیره شد: تلگرام({telegram_id}) -> روبیکا({rubika_id})")
            
            stats["forwarded_messages"] += 1
            save_data_to_file('stats.json', stats)
        else:
            print("--> پیام از نوع پشتیبانی نشده و نادیده گرفته شد.")
            
    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
    print(f"==============================================\n")

async def telegram_edited_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edited_message = update.edited_channel_post
    if not (edited_message and rubika_bot): return
    print(f"\n==============================================")
    print(f"یک پیام ویرایش شده از تلگرام دریافت شد.")
    try:
        telegram_id = str(edited_message.message_id)
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

async def admin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '/stats':
        count = stats.get("forwarded_messages", 0)
        await update.message.reply_text(f"📊 آمار ربات:\n\nتعداد کل پیام های فوروارد شده: {count} عدد")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.CHANNEL_POST,
        telegram_channel_handler
    ))
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.EDITED_CHANNEL_POST,
        telegram_edited_channel_handler
    ))
    
    # استفاده از لیست ادمین ها در فیلتر
    app.add_handler(MessageHandler(
        filters.User(user_id=TELEGRAM_ADMIN_IDS) & filters.COMMAND,
        admin_command_handler
    ))
    
    print("==================================================")
    print("ربات فورواردر کامل (با چند ادمین) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

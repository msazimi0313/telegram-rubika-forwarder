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
message_map = {}

def convert_telegram_entities_to_markdown(text, entities):
    if not entities: return text
    for entity in sorted(entities, key=lambda e: e.offset, reverse=True):
        start = entity.offset
        end = start + entity.length
        entity_text = text[start:end]
        markdown_text = entity_text
        if entity.type == 'bold':
            markdown_text = f"**{entity_text}**"
        elif entity.type == 'italic':
            markdown_text = f"_{entity_text}_"
        elif entity.type == 'text_link':
            markdown_text = f"[{entity_text}]({entity.url})"
        elif entity.type == 'spoiler':
            markdown_text = f"||{entity_text}||"
        elif entity.type == 'code':
            markdown_text = f"`{entity_text}`"
        elif entity.type == 'pre':
            markdown_text = f"```{entity_text}```"
        text = text[:start] + markdown_text + text[end:]
    return text

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
    if not (message and rubika_bot): return
    print(f"\n==============================================")
    print(f"یک پیام جدید از کانال تلگرام دریافت شد.")
    try:
        sent_rubika_message = None
        if message.text:
            final_text = convert_telegram_entities_to_markdown(message.text, message.entities)
            sent_rubika_message = await rubika_bot.send_message(RUBIKA_DESTINATION_CHANNEL_ID, final_text, parse_mode='Markdown')
            print("--> پیام متنی (با فرمت) با موفقیت به کانال روبیکا ارسال شد.")
        elif message.photo or message.video:
            file_to_process = message.photo[-1] if message.photo else message.video
            file_type = 'Image' if message.photo else 'Video'
            final_caption = convert_telegram_entities_to_markdown(message.caption or "", message.caption_entities)
            tg_file = await file_to_process.get_file()
            file_path = await tg_file.download_to_drive()
            sent_rubika_message = await rubika_bot.send_file(
                RUBIKA_DESTINATION_CHANNEL_ID,
                file=str(file_path),
                text=final_caption,
                type=file_type,
                parse_mode='Markdown'
            )
            print(f"--> فایل از نوع '{file_type}' با موفقیت به کانال روبیکا ارسال شد.")
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
    if not (edited_message and rubika_bot): return
    print(f"\n==============================================")
    print(f"یک پیام ویرایش شده از تلگرام دریافت شد.")
    try:
        telegram_id = edited_message.message_id
        if telegram_id in message_map:
            rubika_id = message_map[telegram_id]
            new_content = convert_telegram_entities_to_markdown(
                edited_message.text or edited_message.caption or "",
                edited_message.entities or edited_message.caption_entities
            )
            await rubika_bot.edit_message_text(RUBIKA_DESTINATION_CHANNEL_ID, rubika_id, new_content, parse_mode='Markdown')
            print(f"--> پیام ({rubika_id}) در روبیکا با موفقیت ویرایش شد.")
        else:
            print("--> شناسه پیام ویرایش شده در دفترچه یافت نشد.")
    except Exception as e:
        print(f"!! یک خطا در هنگام ویرایش پیام رخ داد: {e}")
    print(f"==============================================\n")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.CHANNEL_POST, telegram_channel_handler))
    app.add_handler(MessageHandler(filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.EDITED_CHANNEL_POST, telegram_edited_channel_handler))
    print("==================================================")
    print("ربات فورواردر (با فرمت متن و ویرایش) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

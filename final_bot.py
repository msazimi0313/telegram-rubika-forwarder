import asyncio
import os
import json
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
from rubpy import BotClient

# ===============================================================
# بخش تنظیمات (بدون تغییر)
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_SOURCE_CHANNEL_ID = int(os.environ.get("TELEGRAM_SOURCE_CHANNEL_ID"))
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
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
telegram_app: Application | None = None
message_map = {}
stats = {} # در ابتدا خالی تعریف می کنیم

def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

# *** تابع post_init با منطق بارگذاری هوشمند آمار ***
async def post_init(application: Application):
    global rubika_bot, message_map, stats, telegram_app
    telegram_app = application
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")
    
    message_map = load_data_from_file('message_map.json', {})
    
    # بارگذاری آمار با ساختار هوشمند و مقاوم در برابر خطا
    loaded_stats = load_data_from_file('stats.json', {})
    default_stats = {
        "total_forwarded": 0,
        "by_type": {"text": 0, "photo": 0, "video": 0, "document": 0, "audio": 0},
        "errors": 0,
        "last_activity_time": None
    }
    # ادغام آمار قدیمی در ساختار جدید برای اطمینان از وجود تمام کلیدها
    stats = default_stats
    stats.update(loaded_stats)
    if 'by_type' in loaded_stats and isinstance(loaded_stats.get('by_type'), dict):
        stats['by_type'].update(loaded_stats['by_type'])

    print("اطلاعات قبلی (شناسه ها و آمار) با موفقیت بارگذاری شد.")
    
    for admin_id in TELEGRAM_ADMIN_IDS:
        try:
            await telegram_app.bot.send_message(chat_id=admin_id, text="✅ ربات با موفقیت آنلاین و راه‌اندازی شد.")
        except Exception as e:
            print(f"خطا در ارسال پیام به ادمین {admin_id}: {e}")

# ... (بقیه توابع شما دقیقاً مثل قبل است و نیازی به تغییر ندارد)
async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا با موفقیت متوقف شد.")

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats, telegram_app
    message = update.channel_post
    if not (message and rubika_bot): return
    print(f"\n==============================================")
    print(f"یک پیام جدید از کانال تلگرام دریافت شد.")
    try:
        caption = message.caption or ""
        sent_rubika_message = None
        message_type = "unknown"
        reply_to_rubika_id = None
        if message.reply_to_message:
            reply_to_telegram_id = str(message.reply_to_message.message_id)
            if reply_to_telegram_id in message_map:
                reply_to_rubika_id = message_map[reply_to_telegram_id]
        if message.text:
            message_type = "text"
            sent_rubika_message = await rubika_bot.send_message(RUBIKA_DESTINATION_CHANNEL_ID, message.text, reply_to_message_id=reply_to_rubika_id)
            print("--> پیام متنی با موفقیت به کانال روبیکا ارسال شد.")
        elif message.photo or message.video or message.document or message.audio:
            file_to_process = message.photo[-1] if message.photo else (message.video or message.document or message.audio)
            if message.photo: message_type = "photo"
            elif message.video: message_type = "video"
            elif message.document: message_type = "document"
            elif message.audio: message_type = "audio"
            rubika_file_type = 'Image' if message.photo else ('Video' if message.video else 'File')
            tg_file = await file_to_process.get_file()
            file_path = await tg_file.download_to_drive()
            sent_rubika_message = await rubika_bot.send_file(
                RUBIKA_DESTINATION_CHANNEL_ID,
                file=str(file_path),
                text=caption,
                type=rubika_file_type,
                reply_to_message_id=reply_to_rubika_id
            )
            print(f"--> فایل از نوع '{message_type}' با موفقیت به کانال روبیکا ارسال شد.")
            os.remove(file_path)
        if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
            telegram_id = message.message_id
            rubika_id = sent_rubika_message.message_id
            message_map[str(telegram_id)] = rubika_id
            save_data_to_file('message_map.json', message_map)
            stats["total_forwarded"] = stats.get("total_forwarded", 0) + 1
            if message_type in stats["by_type"]: stats["by_type"][message_type] = stats["by_type"].get(message_type, 0) + 1
            stats["last_activity_time"] = datetime.now().isoformat()
            save_data_to_file('stats.json', stats)
        else:
            print("--> پیام از نوع پشتیبانی نشده و نادیده گرفته شد.")
    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
        stats["errors"] = stats.get("errors", 0) + 1
        stats["last_activity_time"] = datetime.now().isoformat()
        save_data_to_file('stats.json', stats)
        error_text = f"❌ یک خطا در هنگام فوروارد کردن پیام رخ داد:\n\n`{e}`"
        for admin_id in TELEGRAM_ADMIN_IDS:
            try:
                await telegram_app.bot.send_message(chat_id=admin_id, text=error_text)
            except Exception as e_admin:
                 print(f"خطا در ارسال پیام خطا به ادمین {admin_id}: {e_admin}")
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

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["📊 آمار (/stats)"], ["⚙️ وضعیت ربات (/status)"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("پنل مدیریت:", reply_markup=reply_markup)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_text = f"📊 **آمار عملکرد ربات فورواردر**\n\n"
    stats_text += f"کل پیام‌های فوروارد شده: **{stats.get('total_forwarded', 0)}**\n\n"
    stats_text += f"**— تفکیک بر اساس نوع —**\n"
    stats_text += f"📝 متن: {stats.get('by_type', {}).get('text', 0)}\n"
    stats_text += f"🖼 عکس: {stats.get('by_type', {}).get('photo', 0)}\n"
    stats_text += f"📹 ویدیو: {stats.get('by_type', {}).get('video', 0)}\n"
    stats_text += f"🎵 صوت: {stats.get('by_type', {}).get('audio', 0)}\n"
    stats_text += f"📄 فایل: {stats.get('by_type', {}).get('document', 0)}\n\n"
    stats_text += f"**— وضعیت سلامت ربات —**\n"
    stats_text += f"❗️ تعداد خطاها: **{stats.get('errors', 0)}**\n"
    last_activity = stats.get('last_activity_time')
    if last_activity:
        last_activity_dt = datetime.fromisoformat(last_activity)
        last_activity_str = last_activity_dt.strftime('%Y-%m-%d %H:%M:%S')
        stats_text += f"⏰ آخرین فعالیت: {last_activity_str}\n"
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_text = (
        f"✅ ربات فعال و در حال کار است.\n\n"
        f"کانال تلگرام: `{TELEGRAM_SOURCE_CHANNEL_ID}`\n"
        f"کانال روبیکا: `{RUBIKA_DESTINATION_CHANNEL_ID}`"
    )
    await update.message.reply_text(status_text)

async def unauthorized_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.first_name
    unauthorized_text = (
        f" سلام {user_name} عزیز! 🌸\n\n"
        f"متاسفانه شما اجازه استفاده از این دستورات را ندارید. "
        f"این ربات یک ابزار شخصی برای مدیریت کانال‌ها است.\n\n"
        f"اگر سوالی دارید، می‌توانید با ادمین اصلی در ارتباط باشید. ✨"
    )
    await update.message.reply_text(unauthorized_text)

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    admin_filter = filters.User(user_id=TELEGRAM_ADMIN_IDS)
    
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.CHANNEL_POST,
        telegram_channel_handler
    ))
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=TELEGRAM_SOURCE_CHANNEL_ID) & filters.UpdateType.EDITED_CHANNEL_POST,
        telegram_edited_channel_handler
    ))
    
    app.add_handler(CommandHandler("admin", admin_panel, filters=admin_filter))
    
    stats_filter = (filters.COMMAND & filters.Regex('^/stats$')) | (filters.TEXT & filters.Regex('^📊 آمار'))
    app.add_handler(MessageHandler(stats_filter & admin_filter, admin_stats))
    
    status_filter = (filters.COMMAND & filters.Regex('^/status$')) | (filters.TEXT & filters.Regex('^⚙️ وضعیت ربات'))
    app.add_handler(MessageHandler(status_filter & admin_filter, admin_status))

    app.add_handler(MessageHandler(filters.COMMAND & (~admin_filter), unauthorized_user_handler))
    
    print("==================================================")
    print("ربات فورواردر کامل (با تمام قابلیت های مدیریتی) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

import re
import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
from rubpy import BotClient
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
    
    # متغیرهای جدید برای Telethon
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    SESSION_STRING = os.environ.get("SESSION_STRING")

except (TypeError, ValueError) as e:
    print(f"خطا: یکی از متغیرهای محیطی ضروری تنظیم نشده یا فرمت آن اشتباه است. {e}")
    exit()

PORT = int(os.environ.get("PORT", 10000))
IRAN_TIMEZONE = pytz.timezone('Asia/Tehran')

# ===============================================================
# بخش اصلی کد
# ===============================================================

# کلاینت‌ها
rubika_bot: BotClient | None = None
telegram_app: Application | None = None
telethon_client: TelegramClient | None = None

# مدیریت داده‌ها
routing_map = {}
source_channel_ids = []
message_map = {}
stats = {}
message_locks = {}  # برای مدیریت همزمانی و جلوگیری از race condition

def get_default_stats():
    return {
        "total_forwarded": 0,
        "by_type": {"text": 0, "photo": 0, "video": 0, "document": 0, "audio": 0, "voice": 0},
        "errors": 0,
        "last_activity_time": None
    }

def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

def strip_markdown(text: str) -> str:
    """این تابع علائم مارک‌داون را از متن حذف کرده و آن را به متن ساده تبدیل می‌کند."""
    if not text:
        return ""
    # حذف لینک‌ها و نگه داشتن متن لینک: [text](url) -> text
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    # حذف بولد، ایتالیک، استرایک و اسپویلر
    # **text** or __text__ -> text
    # *text* or _text_ -> text
    # ~~text~~ -> text
    # ||text|| -> text
    text = re.sub(r'(\*\*|__|\*|_|~~|\|\|)(.+?)\1', r'\2', text)
    # حذف کد خطی: `text` -> text
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text
    
async def post_init(application: Application):
    """این تابع پس از راه‌اندازی ربات تلگرام، کلاینت‌های روبیکا و تلگرام (یوزر) را فعال می‌کند"""
    global rubika_bot, message_map, stats, telegram_app, telethon_client
    telegram_app = application
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")
    
    print("در حال ساخت و فعال سازی کلاینت تلگرام (Telethon)...")
    telethon_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await telethon_client.start()
    print("کلاینت تلگرام (Telethon) با موفقیت فعال شد.")

    # ثبت هندلرهای تلگرام (یوزر)
    telethon_client.add_event_handler(new_message_handler, events.NewMessage(chats=source_channel_ids))
    telethon_client.add_event_handler(edited_message_handler, events.MessageEdited(chats=source_channel_ids))
    telethon_client.add_event_handler(deleted_message_handler, events.MessageDeleted(chats=source_channel_ids))

    # بارگذاری داده‌های قبلی
    message_map = load_data_from_file('message_map.json', {})
    stats = load_data_from_file('stats.json', get_default_stats())

    # ارسال پیام شروع به کار به ادمین‌ها
    for admin_id in TELEGRAM_ADMIN_IDS:
        try:
            await telegram_app.bot.send_message(chat_id=admin_id, text="✅ ربات چندکاناله با موفقیت آنلاین شد. (نسخه نهایی)")
        except Exception as e:
            print(f"خطا در ارسال پیام به ادمین {admin_id}: {e}")

async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا متوقف شد.")
    if telethon_client:
        print("در حال متوقف کردن کلاینت تلگرام (Telethon)...")
        await telethon_client.disconnect()
        print("کلاینت تلگرام (Telethon) متوقف شد.")

# --- هندلرهای جدید با استفاده از Telethon ---

async def new_message_handler(event: events.NewMessage.Event):
    """هندلر پیام‌های جدید - با قابلیت حذف مارک‌داون"""
    global stats, telegram_app, message_map
    message = event.message
    source_id = message.chat_id
    destination_id = routing_map.get(source_id)
    if not (message and rubika_bot and destination_id): return
    
    lock = asyncio.Lock()
    message_locks[message.id] = lock
    async with lock:
        print(f"\n==============================================")
        print(f"پیام جدید از کانال تلگرام ({source_id}) -> ارسال به روبیکا ({destination_id})")
        
        try:
            # استفاده از تابع strip_markdown برای پاک‌سازی متن و کپشن
            plain_text = strip_markdown(message.text or "")
            
            sent_rubika_message = None
            message_type = "unknown"
            file_path = None

            if message.text and not message.media:
                message_type = "text"
                sent_rubika_message = await rubika_bot.send_message(destination_id, plain_text)
            elif message.photo:
                message_type = "photo"
                file_path = await message.download_media()
                sent_rubika_message = await rubika_bot.send_file(destination_id, file=str(file_path), text=plain_text, type='Image')
            elif message.video:
                message_type = "video"
                file_path = await message.download_media()
                sent_rubika_message = await rubika_bot.send_file(destination_id, file=str(file_path), text=plain_text, type='Video')
            elif message.audio:
                message_type = "audio"
                # ترکیب کپشن ساده با اطلاعات فایل صوتی
                audio_info = f"🎵 {message.audio.performer or ''} - {message.audio.title or ''}\n\n".strip()
                final_caption = audio_info + plain_text
                file_path = await message.download_media()
                sent_rubika_message = await rubika_bot.send_music(destination_id, file=str(file_path), text=final_caption)
            elif message.voice:
                message_type = "voice"
                file_path = await message.download_media()
                sent_rubika_message = await rubika_bot.send_voice(destination_id, file=str(file_path))
            elif message.document:
                message_type = "document"
                file_path = await message.download_media()
                sent_rubika_message = await rubika_bot.send_file(destination_id, file=str(file_path), text=plain_text, type='File')

            if file_path: os.remove(file_path)

            if message_type != "unknown":
                print(f"--> پیام از نوع '{message_type}' با موفقیت به روبیکا ارسال شد (به صورت متن ساده).")
                if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
                    telegram_id = message.id
                    rubika_id = sent_rubika_message.message_id
                    message_map[str(telegram_id)] = {"rubika_id": rubika_id, "destination_id": destination_id}
                    save_data_to_file('message_map.json', message_map)
                    
                    stats.setdefault("by_type", {}).setdefault(message_type, 0)
                    stats["by_type"][message_type] += 1
                    stats["total_forwarded"] = stats.get("total_forwarded", 0) + 1
                    stats["last_activity_time"] = datetime.now(IRAN_TIMEZONE).isoformat()
                    save_data_to_file('stats.json', stats)
            else:
                print("--> پیام از نوع پشتیبانی نشده و نادیده گرفته شد.")

        except Exception as e:
            print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
            stats["errors"] = stats.get("errors", 0) + 1
            save_data_to_file('stats.json', stats)
            error_text = f"❌ خطا در فوروارد از {source_id}:\n\n`{e}`"
            for admin_id in TELEGRAM_ADMIN_IDS:
                await telegram_app.bot.send_message(chat_id=admin_id, text=error_text)
        print(f"==============================================\n")
    
    message_locks.pop(message.id, None)

async def edited_message_handler(event: events.MessageEdited.Event):
    """هندلر ویرایش پیام - با قابلیت حذف مارک‌داون"""
    edited_message = event.message
    if not (edited_message and rubika_bot): return
    
    lock = message_locks.get(edited_message.id)
    if lock:
        async with lock:
            pass # منتظر می‌مانیم تا قفل آزاد شود

    print(f"\n==============================================")
    print(f"یک پیام ویرایش شده از تلگرام دریافت شد.")
    try:
        telegram_id = str(edited_message.id)
        mapping = message_map.get(telegram_id)
        if mapping:
            rubika_id = mapping["rubika_id"]
            destination_id = mapping["destination_id"]
            # استفاده از تابع strip_markdown برای پاک‌سازی متن ویرایش شده
            new_content = strip_markdown(edited_message.text or "")
            await rubika_bot.edit_message_text(destination_id, rubika_id, new_content)
            print(f"--> پیام ({rubika_id}) در کانال ({destination_id}) با موفقیت ویرایش شد (به صورت متن ساده).")
        else:
            print("--> شناسه پیام ویرایش شده در دفترچه یافت نشد.") 
    except Exception as e:
        print(f"!! یک خطا در هنگام ویرایش پیام رخ داد: {e}")
    print(f"==============================================\n")
    print(f"یک پیام ویرایش شده از تلگرام دریافت شد.")
    try:
        telegram_id = str(edited_message.id)
        mapping = message_map.get(telegram_id)
        if mapping:
            rubika_id = mapping["rubika_id"]
            destination_id = mapping["destination_id"]
            new_content = edited_message.text or ""
            await rubika_bot.edit_message_text(destination_id, rubika_id, new_content)
            print(f"--> پیام ({rubika_id}) در کانال ({destination_id}) با موفقیت ویرایش شد.")
        else:
            print("--> شناسه پیام ویرایش شده در دفترچه یافت نشد.") 
    except Exception as e:
        print(f"!! یک خطا در هنگام ویرایش پیام رخ داد: {e}")
    print(f"==============================================\n")

async def deleted_message_handler(event: events.MessageDeleted.Event):
    """هندلر حذف پیام (نسخه نهایی با متد صحیح)"""
    if not rubika_bot: return
    print(f"\n==============================================")
    print(f"یک یا چند پیام از تلگرام حذف شد.")
    try:
        map_changed = False
        for telegram_id in event.deleted_ids:
            mapping = message_map.pop(str(telegram_id), None)
            if mapping:
                map_changed = True
                rubika_id = mapping["rubika_id"]
                destination_id = mapping["destination_id"]
                await rubika_bot.delete_message(destination_id, rubika_id)
                print(f"--> پیام متناظر ({rubika_id}) در کانال روبیکا ({destination_id}) با موفقیت حذف شد.")
            else:
                print(f"--> شناسه پیام حذف شده ({telegram_id}) در دفترچه یافت نشد.")
        
        if map_changed:
            save_data_to_file('message_map.json', message_map)
            
    except Exception as e:
        print(f"!! یک خطا در هنگام حذف پیام رخ داد: {e}")
    print(f"==============================================\n")

# --- هندلرهای پنل ادمین ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["📊 آمار"], ["⚙️ وضعیت ربات"], ["🗑 پاک کردن آمار"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("پنل مدیریت:", reply_markup=reply_markup)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_text = f"📊 **آمار عملکرد ربات فورواردر**\n\n"
    stats_text += f"کل پیام‌های فوروارد شده: **{stats.get('total_forwarded', 0)}**\n"
    stats_text += f"تعداد خطاها: **{stats.get('errors', 0)}**\n\n"
    stats_text += "**— تفکیک نوع پیام —**\n"
    for msg_type, count in stats.get("by_type", {}).items():
        stats_text += f"  - {msg_type.capitalize()}: {count}\n"
    
    last_activity = stats.get("last_activity_time")
    if last_activity:
        dt_object = datetime.fromisoformat(last_activity).astimezone(IRAN_TIMEZONE)
        jalali_time = jdatetime.datetime.fromgregorian(datetime=dt_object)
        stats_text += f"\nآخرین فعالیت: **{jalali_time.strftime('%Y/%m/%d - %H:%M:%S')}**"
    else:
        stats_text += "\nآخرین فعالیت: **-**"
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_text = "✅ ربات فعال و در حال کار است.\n\n"
    status_text += "**— نقشه مسیردهی فعال —**\n"
    for tg_id, rb_id in routing_map.items():
        status_text += f"`{tg_id}` ➡️ `{rb_id}`\n"
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def admin_clear_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats
    stats = get_default_stats()
    save_data_to_file('stats.json', stats)
    await update.message.reply_text("🗑 آمار ربات با موفقیت پاک و صفر شد.")

async def unauthorized_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.first_name
    await update.message.reply_text(f" سلام {user_name} عزیز! 🌸\n\nمتاسفانه شما اجازه استفاده از این دستورات را ندارید.")

def main():
    global routing_map, source_channel_ids
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            if ':' in pair:
                tg_id, rb_id = pair.split(':', 1)
                routing_map[int(tg_id.strip())] = rb_id.strip()
        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش متغیر محیطی CHANNEL_MAP: {e}")
        return

    # ساخت اپلیکیشن ربات تلگرام برای پنل ادمین
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    admin_filter = filters.User(user_id=TELEGRAM_ADMIN_IDS)
    
    app.add_handler(CommandHandler("admin", admin_panel, filters=admin_filter))
    app.add_handler(CommandHandler("status", admin_status, filters=admin_filter))
    stats_filter = (filters.COMMAND & filters.Regex('^/stats$')) | (filters.TEXT & filters.Regex('^📊 آمار$'))
    app.add_handler(MessageHandler(stats_filter & admin_filter, admin_stats))
    clear_stats_filter = (filters.COMMAND & filters.Regex('^/clearstats$')) | (filters.TEXT & filters.Regex('^🗑 پاک کردن آمار$'))
    app.add_handler(MessageHandler(clear_stats_filter & admin_filter, admin_clear_stats))
    
    app.add_handler(MessageHandler(filters.COMMAND & (~admin_filter), unauthorized_user_handler))
    
    print("==================================================")
    print("ربات فورواردر (نسخه نهایی) آنلاین شد...")
    print("==================================================")
    
    # اجرای وب‌هوک برای ربات تلگرام (پنل ادمین)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()


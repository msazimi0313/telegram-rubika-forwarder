import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
from rubpy import BotClient

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    # خواندن نقشه کانال ها از متغیر محیطی جدید
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
    PYTHONUNBUFFERED = os.environ.get("PYTHONUNBUFFERED")
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی تنظیم نشده یا فرمت آن اشتباه است.")
    exit()

PORT = int(os.environ.get("PORT", 10000))
IRAN_TIMEZONE = pytz.timezone('Asia/Tehran')

# ===============================================================
# بخش اصلی کد
# ===============================================================

rubika_bot: BotClient | None = None
telegram_app: Application | None = None
# دیکشنری برای تبدیل شناسه تلگرام به روبیکا
routing_map = {}
# لیست شناسه های کانال های مبدا در تلگرام
source_channel_ids = []

message_map = {}
stats = {}

# --- توابع مدیریت فایل و آمار (بدون تغییر) ---
def get_default_stats():
    return {"total_forwarded": 0, "by_type": {}, "errors": 0, "last_activity_time": None}
def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data
def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

async def post_init(application: Application):
    global rubika_bot, message_map, stats, telegram_app
    telegram_app = application
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")
    
    message_map = load_data_from_file('message_map.json', {})
    stats = load_data_from_file('stats.json', get_default_stats())
    
    for admin_id in TELEGRAM_ADMIN_IDS:
        try:
            await telegram_app.bot.send_message(chat_id=admin_id, text="✅ ربات چندکاناله با موفقیت آنلاین شد.")
        except Exception as e:
            print(f"خطا در ارسال پیام به ادمین {admin_id}: {e}")

async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا با موفقیت متوقف شد.")

# --- هندلر اصلی با قابلیت تشخیص کانال ---
async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats, telegram_app
    message = update.channel_post
    if not (message and rubika_bot): return

    source_id = message.chat_id
    destination_id = routing_map.get(source_id)

    if not destination_id:
        print(f"پیام از کانال ناشناس {source_id} دریافت شد و نادیده گرفته شد.")
        return

    print(f"\n==============================================")
    print(f"پیام جدید از کانال تلگرام ({source_id}) دریافت شد -> ارسال به کانال روبیکا ({destination_id})")
    
    try:
        caption = message.caption or ""
        sent_rubika_message = None
        message_type = "unknown"
        
        # ... (منطق ریپلای بدون تغییر)

        if message.text:
            message_type = "text"
            sent_rubika_message = await rubika_bot.send_message(destination_id, message.text)
        elif message.photo or message.video: # ... و انواع دیگر فایل
            # ... (منطق ارسال فایل بدون تغییر، فقط مقصد آن داینامیک است)
            file_to_process = message.photo[-1] if message.photo else message.video
            message_type = 'photo' if message.photo else 'video'
            rubika_file_type = 'Image' if message.photo else 'Video'
            
            tg_file = await file_to_process.get_file()
            file_path = await tg_file.download_to_drive()
            
            sent_rubika_message = await rubika_bot.send_file(
                destination_id,
                file=str(file_path),
                text=caption,
                type=rubika_file_type
            )
            os.remove(file_path)
            
        print(f"--> پیام از نوع '{message_type}' با موفقیت به روبیکا ارسال شد.")

        if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
            telegram_id = message.message_id
            rubika_id = sent_rubika_message.message_id
            # ذخیره شناسه مقصد به همراه شناسه پیام برای ویرایش
            message_map[str(telegram_id)] = {"rubika_id": rubika_id, "destination_id": destination_id}
            save_data_to_file('message_map.json', message_map)
            
            # آپدیت آمار
            if message_type not in stats.get("by_type", {}): stats["by_type"][message_type] = 0
            stats["by_type"][message_type] += 1
            stats["total_forwarded"] = stats.get("total_forwarded", 0) + 1
            stats["last_activity_time"] = datetime.now(IRAN_TIMEZONE).isoformat()
            save_data_to_file('stats.json', stats)
        else:
            print("--> پیام از نوع پشتیبانی نشده و نادیده گرفته شد.")
            
    except Exception as e:
        # ... (منطق ارسال خطا به ادمین بدون تغییر)
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
        stats["errors"] = stats.get("errors", 0) + 1
        save_data_to_file('stats.json', stats)
        error_text = f"❌ خطا در فوروارد از {source_id}:\n\n`{e}`"
        for admin_id in TELEGRAM_ADMIN_IDS:
            await telegram_app.bot.send_message(chat_id=admin_id, text=error_text)

    print(f"==============================================\n")

# --- هندلر ویرایش با قابلیت تشخیص کانال ---
async def telegram_edited_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edited_message = update.edited_channel_post
    if not (edited_message and rubika_bot): return
    
    print(f"\n==============================================")
    print(f"یک پیام ویرایش شده از تلگرام دریافت شد.")
    try:
        telegram_id = str(edited_message.message_id)
        mapping = message_map.get(telegram_id)
        
        if mapping:
            rubika_id = mapping["rubika_id"]
            destination_id = mapping["destination_id"]
            new_content = edited_message.text or edited_message.caption or ""
            await rubika_bot.edit_message_text(destination_id, rubika_id, new_content)
            print(f"--> پیام ({rubika_id}) در کانال ({destination_id}) با موفقیت ویرایش شد.")
        else:
            print("--> شناسه پیام ویرایش شده در دفترچه یافت نشد.")
    except Exception as e:
        print(f"!! یک خطا در هنگام ویرایش پیام رخ داد: {e}")
    print(f"==============================================\n")

# --- توابع ادمین (آپدیت برای نمایش نقشه) ---
async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_text = "✅ ربات فعال و در حال کار است.\n\n"
    status_text += "**— نقشه مسیردهی فعال —**\n"
    for tg_id, rb_id in routing_map.items():
        status_text += f"`{tg_id}` ➡️ `{rb_id}`\n"
    await update.message.reply_text(status_text, parse_mode='Markdown')

# ... (بقیه توابع ادمین بدون تغییر)
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["📊 آمار (/stats)"], ["⚙️ وضعیت ربات (/status)"], ["🗑 پاک کردن آمار (/clearstats)"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("پنل مدیریت:", reply_markup=reply_markup)
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (منطق آمار بدون تغییر)
async def admin_clear_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats
    stats = get_default_stats()
    save_data_to_file('stats.json', stats)
    await update.message.reply_text("🗑 آمار ربات با موفقیت پاک و صفر شد.")
async def unauthorized_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (منطق کاربران غیرمجاز بدون تغییر)

def main():
    global routing_map, source_channel_ids
    # پردازش نقشه کانال ها
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            tg_id, rb_id = pair.split(':')
            routing_map[int(tg_id.strip())] = rb_id.strip()
        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش متغیر محیطی CHANNEL_MAP: {e}")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    admin_filter = filters.User(user_id=TELEGRAM_ADMIN_IDS)
    
    # هندلرها حالا به لیستی از کانال ها گوش می دهند
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=source_channel_ids) & filters.UpdateType.CHANNEL_POST,
        telegram_channel_handler
    ))
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=source_channel_ids) & filters.UpdateType.EDITED_CHANNEL_POST,
        telegram_edited_channel_handler
    ))
    
    # هندلرهای ادمین
    app.add_handler(CommandHandler("admin", admin_panel, filters=admin_filter))
    app.add_handler(CommandHandler("status", admin_status, filters=admin_filter))
    # ... (بقیه هندلرهای ادمین)
    
    print("==================================================")
    print("ربات فورواردر چندکاناله آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

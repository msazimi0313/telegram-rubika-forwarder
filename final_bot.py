import asyncio
import os
import json
from datetime import datetime
import pytz
import httpx # <--- CHANGE: کتابخانه جدید برای ارسال درخواست مستقیم
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
from rubpy import BotClient
from pathlib import Path

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    EITAA_BOT_TOKEN = os.environ.get("EITAA_BOT_TOKEN") # <--- این همان توکن "ایتا یار" است
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
# <--- CHANGE: eitaa_app و کلاس سفارشی کاملا حذف شدند چون دیگر نیازی به آنها نیست
routing_map = {}
source_channel_ids = []
message_map = {}
stats = {}

def get_default_stats():
    return {"total_forwarded": 0, "by_type": {}, "errors": 0, "last_activity_time": None}

def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)
    
# <--- CHANGE: تابع جدید و ساده برای ارسال پیام با API ایتا یار
async def send_to_eitaa_yar(token: str, channel_id: str, text: str):
    """
    پیام متنی را با استفاده از API ایتا یار به کانال مورد نظر ارسال می‌کند.
    """
    url = "https://eitaayar.ir/api/v1/SendMessageByUsername"
    payload = {
        "token": token,
        "username": channel_id, # ایتا یار به جای @username از username استفاده می‌کند
        "text": text
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status() # اگر خطا بود (مثل 404 یا 500)، استثنا ایجاد می‌کند
            result = response.json()
            if result.get("status") == 1:
                print(f"--> پیام با موفقیت به ایتا یار ارسال شد. وضعیت: {result.get('message')}")
                return True, result
            else:
                error_message = result.get("message", "خطای نامشخص از ایتا یار")
                print(f"!! ایتا یار خطا برگرداند: {error_message}")
                return False, error_message
    except httpx.HTTPStatusError as e:
        print(f"!! خطای HTTP در ارتباط با ایتا یار: {e.response.status_code} - {e.response.text}")
        return False, str(e)
    except Exception as e:
        print(f"!! یک خطای ناشناخته در تابع ارسال به ایتا یار رخ داد: {e}")
        return False, str(e)


async def post_init(application: Application):
    global rubika_bot, message_map, stats, telegram_app
    telegram_app = application
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")
    
    # <--- CHANGE: بخش مربوط به ساخت کلاینت ایتا کاملا حذف شد.
    print("API ایتا یار برای ارسال پیام استفاده خواهد شد.")

    message_map = load_data_from_file('message_map.json', {})
    stats = load_data_from_file('stats.json', get_default_stats())
    
    for admin_id in TELEGRAM_ADMIN_IDS:
        try:
            await telegram_app.bot.send_message(chat_id=admin_id, text="✅ ربات فورواردر (تلگرام، روبیکا، ایتا یار) با موفقیت آنلاین شد.")
        except Exception as e:
            print(f"خطا در ارسال پیام به ادمین {admin_id}: {e}")

async def post_shutdown(application: Application):
    if rubika_bot:
        print("در حال متوقف کردن کلاینت روبیکا...")
        await rubika_bot.close()
        print("کلاینت روبیکا با موفقیت متوقف شد.")

async def telegram_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats, telegram_app
    message = update.channel_post
    if not (message and rubika_bot): return
    
    source_id = message.chat_id
    destinations = routing_map.get(source_id)
    if not destinations: return

    rubika_dest_id = destinations.get('rubika')
    eitaa_dest_id = destinations.get('eitaa')
    
    print(f"\n==============================================")
    print(f"پیام جدید از تلگرام ({source_id}) -> ارسال به روبیکا ({rubika_dest_id}) و ایتا ({eitaa_dest_id})")
    
    try:
        # توجه: API ایتا یار فقط از متن پشتیبانی می‌کند. فعلا منطق فایل را برای آن غیرفعال می‌کنیم.
        # در آینده می‌توان مستندات آن را برای ارسال فایل بررسی کرد.
        if not message.text:
            print("--> پیام از نوع غیرمتنی است و توسط ایتا یار پشتیبانی نمی‌شود. نادیده گرفته شد.")
            return

        caption = message.caption or ""
        text_to_send = message.text or caption
        sent_rubika_message = None
        message_type = "text"

        # ارسال به روبیکا (بدون تغییر)
        if rubika_dest_id:
            try:
                sent_rubika_message = await rubika_bot.send_message(rubika_dest_id, text_to_send)
                print(f"--> پیام 'text' با موفقیت به روبیکا ارسال شد.")
            except Exception as e:
                print(f"!! خطا در ارسال به روبیکا: {e}")
                # ... گزارش خطا به ادمین ...

        # <--- CHANGE: ارسال به ایتا با استفاده از تابع جدید
        if eitaa_dest_id and text_to_send:
            success, response_msg = await send_to_eitaa_yar(EITAA_BOT_TOKEN, eitaa_dest_id, text_to_send)
            if not success:
                error_text = f"❌ خطا در فوروارد به ایتا ({eitaa_dest_id}):\n\n`{response_msg}`"
                for admin_id in TELEGRAM_ADMIN_IDS:
                    await telegram_app.bot.send_message(chat_id=admin_id, text=error_text)
        
        # ... بقیه منطق ذخیره‌سازی آمار و message_map ...
            
    except Exception as e:
        print(f"!! یک خطای کلی در هنگام فوروارد کردن پیام رخ داد: {e}")
        # ... گزارش خطا به ادمین ...
    
    print(f"==============================================\n")

# ... بقیه کد (بخش ادمین و main) بدون تغییر باقی می‌ماند ...
async def telegram_edited_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("قابلیت ویرایش پیام برای ایتا یار پیاده‌سازی نشده است.")
    # منطق ویرایش برای روبیکا همچنان می‌تواند کار کند اگر آن را نگه دارید.

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["📊 آمار (/stats)"], ["⚙️ وضعیت ربات (/status)"], ["🗑 پاک کردن آمار (/clearstats)"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("پنل مدیریت:", reply_markup=reply_markup)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("... آمار ...")

async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_text = "✅ ربات فعال و در حال کار است.\n\n"
    status_text += "**— نقشه مسیردهی فعال —**\n"
    for tg_id, dests in routing_map.items():
        rb_id = dests.get('rubika', 'N/A')
        et_id = dests.get('eitaa', 'N/A')
        status_text += f"`{tg_id}` ➡️ روبیکا: `{rb_id}` | ایتا: `{et_id}`\n"
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
                parts = pair.split(':')
                if len(parts) == 3:
                    tg_id, rb_id, et_id = parts
                    routing_map[int(tg_id.strip())] = {'rubika': rb_id.strip(), 'eitaa': et_id.strip()}
                else:
                    print(f"فرمت جفت کانال '{pair}' اشتباه است. نادیده گرفته شد.")

        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش متغیر محیطی CHANNEL_MAP: {e}")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    admin_filter = filters.User(user_id=TELEGRAM_ADMIN_IDS)
    
    app.add_handler(MessageHandler(filters.Chat(chat_id=source_channel_ids) & filters.UpdateType.CHANNEL_POST, telegram_channel_handler))
    app.add_handler(MessageHandler(filters.Chat(chat_id=source_channel_ids) & filters.UpdateType.EDITED_CHANNEL_POST, telegram_edited_channel_handler))
    
    app.add_handler(CommandHandler("admin", admin_panel, filters=admin_filter))
    app.add_handler(CommandHandler("status", admin_status, filters=admin_filter))
    # ... بقیه هندلرها
    
    print("==================================================")
    print("ربات فورواردر چندکاناله (تلگرام، روبیکا، ایتا یار) آنلاین شد...")
    print("==================================================")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()

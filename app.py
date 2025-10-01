import asyncio
from threading import Thread
from flask import Flask

# تابع اصلی ربات را از فایل final_bot وارد می‌کنیم
from final_bot import main as run_bot_main

# ۱. تنظیم وب سرور Flask
app = Flask(__name__)

@app.route('/')
def index():
    # این پاسخی است که Koyeb برای بررسی سلامت سرویس می‌بیند
    return "Bot is running successfully!"

# ۲. تابعی برای اجرای ربات در یک Thread جداگانه
def run_bot_in_background():
    """
    ربات تلگرام را در یک لوپ رویداد async جدید اجرا می‌کند.
    این کار از تداخل با لوپ اصلی Flask/Gunicorn جلوگیری می‌کند.
    """
    print("Starting bot in a new thread...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot_main())
    loop.close()
    print("Bot thread finished.")

# ۳. شروع اجرای ربات در پس‌زمینه
bot_thread = Thread(target=run_bot_in_background)
bot_thread.daemon = True  # اطمینان از بسته شدن thread با برنامه اصلی
bot_thread.start()

# Gunicorn این فایل را اجرا کرده و متغیر 'app' را به عنوان وب سرور استفاده می‌کند.

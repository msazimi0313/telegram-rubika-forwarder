import asyncio
from threading import Thread
from flask import Flask
from final_bot import main as run_bot_main

# ۱. ساخت صف برای رویدادها
event_queue = asyncio.Queue()

# ۲. تنظیم وب سرور Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running successfully and queue is active!"

# ۳. تعریف کارگر (Worker) که صف را پردازش می‌کند
async def queue_worker():
    print("Queue worker started. Waiting for events...")
    while True:
        try:
            event_type, event = await event_queue.get()
            # این تابع از final_bot.py فراخوانی می‌شود
            from final_bot import process_event 
            await process_event(event, event_type)
            event_queue.task_done()
        except Exception as e:
            print(f"Error in queue worker: {e}")

# ۴. تابعی برای اجرای ربات و کارگر در یک Thread جداگانه
def run_bot_and_worker():
    print("Starting bot and worker in a new thread...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # اجرای همزمان ربات اصلی و کارگر پردازش صف
    main_task = loop.create_task(run_bot_main(event_queue))
    worker_task = loop.create_task(queue_worker())
    
    loop.run_until_complete(asyncio.gather(main_task, worker_task))
    loop.close()
    print("Bot thread finished.")

# ۵. شروع اجرای ربات و کارگر در پس‌زمینه
bot_thread = Thread(target=run_bot_and_worker)
bot_thread.daemon = True
bot_thread.start()

# Gunicorn این فایل را اجرا کرده و متغیر 'app' را به عنوان وب سرور استفاده می‌کند.

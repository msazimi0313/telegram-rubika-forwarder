# ===============================================================
# فایل دیباگ موقت برای بررسی ساختار کتابخانه rubpy
# ===============================================================
import asyncio
import sys

async def main(event_queue):
    try:
        print("\n" + "="*20 + " STARTING LIBRARY DEBUG " + "="*20)
        
        # ماژول اصلی rubpy را وارد کرده و محتویات آن را چاپ می‌کنیم
        import rubpy
        print("\n[INFO] Contents of 'rubpy' module:")
        print(dir(rubpy))
        
        # تلاش می‌کنیم ببینیم آیا ماژول models به صورت داخلی وجود دارد یا خیر
        try:
            from rubpy import models
            print("\n[SUCCESS] 'rubpy.models' exists. Contents:")
            print(dir(models))
        except ImportError:
            print("\n[FAILED] Could not import 'rubpy.models'.")

        # تلاش می‌کنیم ببینیم آیا ماژول client به صورت داخلی وجود دارد یا خیر
        try:
            from rubpy import client
            print("\n[SUCCESS] 'rubpy.client' exists. Contents:")
            print(dir(client))
            
            # اگر client وجود داشت، ببینیم آیا models داخل آن است
            if 'models' in dir(client):
                print("\n[INFO] 'rubpy.client.models' exists. Contents:")
                print(dir(client.models))

        except ImportError:
            print("\n[FAILED] Could not import 'rubpy.client'.")

        print("\n" + "="*20 + "  ENDING LIBRARY DEBUG  " + "="*20)
        
    except Exception as e:
        print(f"An error occurred during debug: {e}")
    
    finally:
        # پس از چاپ اطلاعات، برنامه را متوقف می‌کنیم تا منابع مصرف نشود
        print("\nDebug finished. Stopping the application.")
        # این خط باعث می‌شود که Thread ربات متوقف شود.
        # ممکن است gunicorn تلاش کند آن را ری‌استارت کند، اما ما لاگ مورد نیاز را گرفته‌ایم.
        sys.exit(0)

# این بخش برای سازگاری با فایل app.py است
if __name__ == "__main__":
    asyncio.run(main(None))

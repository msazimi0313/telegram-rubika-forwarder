# ===============================================================
# فایل دیباگ نهایی برای بررسی محتویات داخلی rubpy
# ===============================================================
import asyncio
import sys

async def main(event_queue):
    try:
        print("\n" + "="*20 + " STARTING FINAL LIBRARY DEBUG " + "="*20)
        
        # ماژول اصلی rubpy را وارد کرده و محتویات آن را چاپ می‌کنیم
        import rubpy
        print("\n[INFO] Contents of 'rubpy' module:")
        print(dir(rubpy))
        
        # محتویات ماژول 'types' را بررسی می‌کنیم
        try:
            from rubpy import types
            print("\n[SUCCESS] Contents of 'rubpy.types':")
            print(dir(types))
        except ImportError:
            print("\n[FAILED] Could not import 'rubpy.types'.")

        # محتویات ماژول 'bot' را بررسی می‌کنیم
        try:
            from rubpy import bot
            print("\n[SUCCESS] Contents of 'rubpy.bot':")
            print(dir(bot))

            # اگر ماژول bot وجود داشت، به دنبال models در داخل آن می‌گردیم
            if 'models' in dir(bot):
                try:
                    from rubpy.bot import models
                    print("\n[SUCCESS] Contents of 'rubpy.bot.models':")
                    print(dir(models))
                except Exception as e:
                    print(f"\n[FAILED] Could not import or inspect 'rubpy.bot.models': {e}")

        except ImportError:
            print("\n[FAILED] Could not import 'rubpy.bot'.")


        print("\n" + "="*20 + "  ENDING FINAL LIBRARY DEBUG  " + "="*20)
        
    except Exception as e:
        print(f"An error occurred during debug: {e}")
    
    finally:
        print("\nDebug finished. Stopping the application.")
        sys.exit(0)

# این بخش برای سازگاری با فایل app.py است
if __name__ == "__main__":
    asyncio.run(main(None))

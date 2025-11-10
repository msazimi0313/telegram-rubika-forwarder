# tg-to-rubika-bridge
Forward Telegram channel messages to corresponding Rubika channels using a Self Telegram account (Telethon) and Rubpy (rubika API).

## Overview
- Listens to messages in two Telegram channels (as a user/session).
- Forwards text and media to two matching Rubika channels via a Bot account (rubpy).
- Health endpoint for UptimeRobot / Render "keep-alive".

## Files
- `main.py` — main application
- `requirements.txt` — Python dependencies
- `Dockerfile` — container for Render
- `.gitignore` — ignore secrets & session files

## Notes
See Rubpy docs for `send_message` / `send_file` behavior. https://rubpy.shayan-heidari.ir/ . :contentReference[oaicite:1]{index=1}

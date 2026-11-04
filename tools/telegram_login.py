"""Один раз запустить на своём компьютере: выводит TELEGRAM_SESSION.

Строка даёт полный доступ к аккаунту. Храните её только в секретах GitHub.
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("api_id с my.telegram.org: ").strip())
api_hash = input("api_hash: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nTELEGRAM_SESSION:\n" + client.session.save())

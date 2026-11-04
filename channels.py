"""Каналы отправки. Канал без настроек просто не запускается."""
from __future__ import annotations

import asyncio
import json
import os
import random
from dataclasses import dataclass
from typing import Callable

import requests

from core import TIMEZONE, Person, today_local


class TelegramSettingsError(Exception):
    pass


@dataclass(frozen=True)
class Result:
    status: str  # sent | failed | not_found | no_recipient | uncertain
    detail: str = ""


def send_sms(person: Person, text: str) -> Result:
    if not person.phone:
        return Result("no_recipient", "нет телефона")
    base = os.environ.get("MOBIZON_API_URL", "https://api.mobizon.kz").rstrip("/")
    payload = {"apiKey": os.environ["MOBIZON_API_KEY"], "recipient": person.phone, "text": text}
    sender = os.environ.get("MOBIZON_SENDER", "").strip()
    if sender:
        payload["from"] = sender
    try:
        response = requests.post(
            f"{base}/service/Message/SendSmsMessage",
            params={"output": "json", "api": "v1"}, data=payload, timeout=30,
        )
    except requests.Timeout:
        return Result("uncertain", "Mobizon не ответил вовремя")
    except requests.RequestException as error:
        return Result("failed", type(error).__name__)  # в тексте ошибки мог быть ключ
    try:
        body = response.json()
    except ValueError:
        return Result("failed", f"HTTP {response.status_code}")
    if body.get("code") == 0:
        return Result("sent", str((body.get("data") or {}).get("messageId", "")))
    return Result("failed", f"код {body.get('code')}: {body.get('message', '')}")


def send_telegram(person: Person, text: str) -> Result:
    if not person.telegram and not person.phone:
        return Result("no_recipient", "нет логина и телефона")
    return asyncio.run(_send_telegram(person, text))


def _telegram_client():
    """Создаёт клиента. Понятно сообщает, какая именно настройка неверна."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = os.environ["TELEGRAM_API_ID"].strip()
    if not api_id.isdigit():
        raise TelegramSettingsError("TELEGRAM_API_ID должен состоять только из цифр")
    try:
        session = StringSession(os.environ["TELEGRAM_SESSION"].strip())
    except ValueError as error:
        raise TelegramSettingsError(
            "TELEGRAM_SESSION неверна: вставьте только строку из tools/telegram_login.py"
        ) from error
    return TelegramClient(session, int(api_id), os.environ["TELEGRAM_API_HASH"].strip())


async def _find_telegram_user(client, person: Person):
    """Сначала логин из столбца F, затем телефон. Возвращает None, если не нашли."""
    from telethon.tl.functions.contacts import ImportContactsRequest
    from telethon.tl.types import InputPhoneContact

    if person.telegram:
        try:
            return await client.get_entity(person.telegram)
        except ValueError:  # такого логина нет
            pass
    if not person.phone:
        return None
    phone = f"+{person.phone}"
    try:
        # Если человек уже в контактах, его имя в записной книжке не меняем.
        return await client.get_entity(phone)
    except ValueError:
        pass
    parts = person.name.split(maxsplit=1)
    imported = await client(ImportContactsRequest([InputPhoneContact(
        client_id=random.randrange(1, 2**62), phone=phone,
        first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "",
    )]))
    return imported.users[0] if imported.users else None


async def _send_telegram(person: Person, text: str) -> Result:
    from telethon.errors import RPCError

    try:
        client = _telegram_client()
    except TelegramSettingsError as error:
        return Result("failed", str(error))
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return Result("failed", "сессия Telegram устарела: создайте её заново")
        target = await _find_telegram_user(client, person)
        if target is None:
            return Result("not_found", "логин не найден, а номера нет в Telegram или он скрыт")
        # Кнопка на сайте и рассылка по расписанию могут сработать в один день.
        today = today_local()
        async for message in client.iter_messages(target, limit=20, from_user="me"):
            if message.message == text and message.date.astimezone(TIMEZONE).date() == today:
                return Result("sent", "уже было отправлено сегодня")
        await client.send_message(target, text)
        return Result("sent")
    except RPCError as error:
        return Result("failed", type(error).__name__)
    except ValueError as error:
        return Result("failed", f"Telegram: {error}")
    finally:
        await client.disconnect()


def send_instagram(person: Person, text: str) -> Result:
    if not person.instagram:
        return Result("no_recipient", "нет логина")
    from instagrapi import Client

    client = Client()
    client.set_settings(json.loads(os.environ["INSTAGRAM_SESSION"]))
    try:
        user_id = client.user_id_from_username(person.instagram)
        client.direct_send(text, user_ids=[int(user_id)])
    except Exception as error:  # у библиотеки десятки своих исключений
        return Result("failed", type(error).__name__)
    return Result("sent")


CHANNELS: dict[str, tuple[Callable[[Person, str], Result], tuple[str, ...]]] = {
    "sms": (send_sms, ("MOBIZON_API_KEY",)),
    "telegram": (send_telegram, ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION")),
    "instagram": (send_instagram, ("INSTAGRAM_SESSION",)),
}


def configured_channels() -> dict[str, Callable[[Person, str], Result]]:
    return {
        name: sender for name, (sender, required) in CHANNELS.items()
        if all(os.environ.get(key, "").strip() for key in required)
    }


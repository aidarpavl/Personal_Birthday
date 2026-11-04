"""Страница Streamlit: напоминания о днях рождения и статус поздравлений."""
from __future__ import annotations

import hmac

import streamlit as st

import core

CHANNEL_NAMES = {"sms": "SMS", "telegram": "Telegram", "instagram": "Instagram"}
STATUS_NAMES = {
    "sent": "✅ отправлено",
    "failed": "❌ ошибка, будет повтор",
    "not_found": "⚠️ не найден в сервисе",
    "no_recipient": "➖ нет контакта",
    "uncertain": "⚠️ нет ответа сервиса, проверьте вручную",
}


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:  # файла с секретами нет
        return default


def require_password() -> None:
    password = secret("APP_PASSWORD")
    if not password:
        st.error("Задайте APP_PASSWORD в настройках приложения: на странице личные данные.")
        st.stop()
    if st.session_state.get("authorized"):
        return
    entered = st.text_input("Пароль", type="password")
    if entered and hmac.compare_digest(entered.encode(), password.encode()):
        st.session_state["authorized"] = True
        st.rerun()
    if entered:
        st.error("Неверный пароль")
    st.stop()


@st.cache_data(ttl=300, show_spinner="Читаю таблицу…")
def load(sheet_id: str, gid: str):
    return core.parse_people(core.load_sheet_csv(sheet_id, gid))


def show_today(person: core.Person, today, log: list[dict[str, str]]) -> None:
    st.success(f"🎉 **{person.name}** — сегодня день рождения, {core.age_on(person, today)} лет")
    rows = {r["channel"]: r for r in log
            if r["date"] == today.isoformat() and r["person"] == person.number}
    for channel, title in CHANNEL_NAMES.items():
        row = rows.get(channel)
        status = STATUS_NAMES.get(row["status"], row["status"]) if row else "⏳ ещё не отправлялось"
        st.write(f"{title}: {status}")
    text = core.greeting_text(person)
    st.code(text, language=None, wrap_lines=True)
    if person.instagram:
        st.link_button(f"Открыть чат в Instagram: @{person.instagram}",
                       f"https://ig.me/m/{person.instagram}")


def main() -> None:
    st.set_page_config(page_title="Туған күндер", page_icon="🎂")
    st.title("🎂 Туған күндер")
    require_password()

    sheet_id = secret("SHEET_ID")
    if not sheet_id:
        st.error("Задайте SHEET_ID в настройках приложения.")
        st.stop()
    try:
        people, issues = load(sheet_id, secret("SHEET_GID", "0") or "0")
    except Exception as error:
        st.error(f"Не удалось прочитать таблицу: {error}")
        st.stop()

    today = core.today_local()
    tomorrow = core.tomorrow_of(today)
    st.caption(f"Сегодня {today:%d.%m.%Y}, людей в таблице: {len(people)}")

    st.subheader("Завтра")
    tomorrow_people = core.birthdays_on(people, tomorrow)
    for person in tomorrow_people:
        st.warning(f"🔔 Завтра, {tomorrow:%d.%m}, день рождения у **{person.name}** "
                   f"({core.age_on(person, tomorrow)} лет)")
    if not tomorrow_people:
        st.write("Завтра дней рождения нет.")

    st.subheader("Сегодня")
    today_people = core.birthdays_on(people, today)
    log = core.read_log()
    for person in today_people:
        show_today(person, today, log)
    if not today_people:
        st.write("Сегодня дней рождения нет.")

    st.subheader("Ближайшие 30 дней")
    soon = [(d, p) for d, p in core.upcoming(people, today, 30) if d > tomorrow]
    if soon:
        st.dataframe(
            [{"Дата": f"{d:%d.%m}", "ФИО": p.name, "Исполнится": core.age_on(p, d)}
             for d, p in soon],
            hide_index=True,
        )
    else:
        st.write("Других дней рождения в ближайшие 30 дней нет.")

    if issues:
        with st.expander(f"Замечания к таблице: {len(issues)}"):
            for issue in issues:
                st.write(issue)


main()

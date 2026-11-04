import sys
from datetime import date
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import channels  # noqa: E402
import core  # noqa: E402
import send_greetings  # noqa: E402
from channels import Result  # noqa: E402

CSV = (
    "№,Аты-жөні,Туған жылы,телефон,логин инстаграмм\n"
    "1,Тест Бір,04.11.1987,87001112233,@test_one\n"
    "2,Тест Екі,05.11.1977,+7 (700) 111-22-44,\n"
    "3,Тест Үш,01.01.2000,,\n"
    "4,Тест Төрт,31.12.1999,123,bad login!\n"
    "5,Тест Бес,29.02.2000,87001112255,\n"
    "6,Тест Алты,нет даты,87001112266,\n"
)


@pytest.fixture
def people():
    return core.parse_people(CSV)[0]


def recording_sender(calls, status="sent"):
    def sender(person, text):
        calls.append((person.number, text))
        return Result(status)
    return sender


def test_parsing_and_issues():
    people, issues = core.parse_people(CSV)
    assert [p.number for p in people] == ["1", "2", "3", "4", "5"]
    assert people[0].phone == "77001112233" and people[0].instagram == "test_one"
    assert people[1].phone == "77001112244"
    assert people[3].phone is None and people[3].instagram is None
    assert any("нет телефона" in i for i in issues)
    assert any("неверная дата" in i for i in issues)
    assert any("неверный логин" in i for i in issues)


@pytest.mark.parametrize("day,expected", [
    (date(2026, 11, 4), ["1"]),
    (date(2026, 11, 5), ["2"]),
    (date(2027, 1, 1), ["3"]),
    (date(2026, 2, 28), ["5"]),   # невисокосный год
    (date(2028, 2, 29), ["5"]),   # високосный
    (date(2028, 2, 28), []),
])
def test_birthdays_ignore_birth_year(people, day, expected):
    assert [p.number for p in core.birthdays_on(people, day)] == expected


def test_tomorrow_crosses_new_year(people):
    tomorrow = core.tomorrow_of(date(2026, 12, 31))
    assert [p.number for p in core.birthdays_on(people, tomorrow)] == ["3"]


def test_greeting_text(people):
    text = core.greeting_text(people[0])
    assert text == "Тест Бір сізді туған күніңізбен құттықтаймыз!!!"
    assert not any("a" <= c.lower() <= "z" for c in text)


def test_sends_only_today_and_never_twice(people, tmp_path):
    log, calls = tmp_path / "log.csv", []
    senders = {"sms": recording_sender(calls)}
    day = date(2026, 11, 4)
    assert send_greetings.run(people, day, senders, log_path=log) == 0
    assert send_greetings.run(people, day, senders, log_path=log) == 0
    assert calls == [("1", "Тест Бір сізді туған күніңізбен құттықтаймыз!!!")]
    # Через год снова поздравляем.
    send_greetings.run(people, date(2027, 11, 4), senders, log_path=log)
    assert len(calls) == 2


def test_failed_is_retried_but_uncertain_is_not(people, tmp_path):
    log, day = tmp_path / "log.csv", date(2026, 11, 4)
    failed, ok = [], []
    assert send_greetings.run(people, day, {"sms": recording_sender(failed, "failed")}, log_path=log) == 1
    send_greetings.run(people, day, {"sms": recording_sender(ok)}, log_path=log)
    assert len(ok) == 1

    log2, unsure, again = tmp_path / "log2.csv", [], []
    send_greetings.run(people, day, {"sms": recording_sender(unsure, "uncertain")}, log_path=log2)
    send_greetings.run(people, day, {"sms": recording_sender(again)}, log_path=log2)
    assert again == []


def test_one_channel_crash_does_not_stop_others(people, tmp_path):
    calls = []
    def broken(person, text):
        raise OSError("boom")
    failures = send_greetings.run(people, date(2026, 11, 4),
                                  {"telegram": broken, "sms": recording_sender(calls)},
                                  log_path=tmp_path / "log.csv")
    assert failures == 1 and len(calls) == 1


def test_dry_run_sends_and_logs_nothing(people, tmp_path):
    log, calls = tmp_path / "log.csv", []
    send_greetings.run(people, date(2026, 11, 4), {"sms": recording_sender(calls)},
                       dry_run=True, log_path=log)
    assert calls == [] and not log.exists()


def test_limit_blocks_mass_send(tmp_path):
    rows = "".join(f"{i},Тест {i},04.11.1990,8700111{i:04d},\n" for i in range(11))
    people, _ = core.parse_people("h\n" + rows)
    with pytest.raises(RuntimeError):
        send_greetings.run(people, date(2026, 11, 4), {"sms": recording_sender([])},
                           log_path=tmp_path / "log.csv")


def test_log_has_no_personal_data(people, tmp_path):
    log = tmp_path / "log.csv"
    send_greetings.run(people, date(2026, 11, 4), {"sms": recording_sender([])}, log_path=log)
    content = log.read_text(encoding="utf-8")
    assert "Тест" not in content and "7700" not in content


class FakeResponse:
    status_code = 200
    def __init__(self, body):
        self._body = body
    def json(self):
        return self._body


def test_mobizon_request_and_results(people, monkeypatch):
    monkeypatch.setenv("MOBIZON_API_KEY", "key")
    monkeypatch.setenv("MOBIZON_SENDER", "")
    seen = {}
    def fake_post(url, params, data, timeout):
        seen.update(url=url, params=params, data=data)
        return FakeResponse({"code": 0, "data": {"messageId": "42"}, "message": ""})
    monkeypatch.setattr(channels.requests, "post", fake_post)
    assert channels.send_sms(people[0], "текст") == Result("sent", "42")
    assert seen["url"] == "https://api.mobizon.kz/service/Message/SendSmsMessage"
    assert seen["data"] == {"apiKey": "key", "recipient": "77001112233", "text": "текст"}

    monkeypatch.setattr(channels.requests, "post",
                        lambda *a, **k: FakeResponse({"code": 2, "message": "нет денег"}))
    assert channels.send_sms(people[0], "т").status == "failed"

    def timeout(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(channels.requests, "post", timeout)
    assert channels.send_sms(people[0], "т").status == "uncertain"
    assert channels.send_sms(people[2], "т").status == "no_recipient"


def test_channels_enabled_only_when_configured(monkeypatch):
    for key in ["MOBIZON_API_KEY", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
                "TELEGRAM_SESSION", "INSTAGRAM_SESSION"]:
        monkeypatch.delenv(key, raising=False)
    assert channels.configured_channels() == {}
    monkeypatch.setenv("MOBIZON_API_KEY", "x")
    monkeypatch.setenv("TELEGRAM_API_ID", "1")  # неполные настройки Telegram
    assert list(channels.configured_channels()) == ["sms"]

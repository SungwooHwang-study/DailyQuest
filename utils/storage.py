# utils/storage.py
from tinydb import TinyDB, Query
from datetime import datetime

db = TinyDB("data/checklist.json")
User = Query()

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def get_week_of_month(date):
    first_day = date.replace(day=1)
    adjusted_dom = date.day + first_day.weekday()
    return int(adjusted_dom / 7) + 1

def get_week_key():
    now = datetime.now()
    week_num = get_week_of_month(now)
    return now.strftime(f"%m-W{week_num}")

def is_checked(user_id: int, game: str, task: str, period: str = "daily") -> bool:
    key = get_today() if period == "daily" else get_week_key()
    result = db.search((User.user_id == user_id) &
                       (User.date == key) &
                       (User.game == game) &
                       (User.task == task))
    return bool(result)

def toggle_check(user_id: int, game: str, task: str, period: str = "daily"):
    if is_checked(user_id, game, task, period):
        remove_check(user_id, game, task, period)
    else:
        add_check(user_id, game, task, period)

def complete_all(user_id: int, game: str, tasks: list[str], period: str = "daily"):
    key = get_today() if period == "daily" else get_week_key()
    for task in tasks:
        if not is_checked(user_id, game, task, period):
            db.insert({
                "user_id": user_id,
                "period": period,
                "date": key,
                "game": game,
                "task": task
            })

def is_event_checked(user_id: int, game: str, event: str, task: str, date: str):
    result = db.search((User.user_id == user_id) &
                       (User.period == "event") &
                       (User.date == date) &
                       (User.game == game) &
                       (User.event == event) &
                       (User.task == task))
    return bool(result)

def toggle_event_check(user_id: int, game: str, event: str, task: str, date: str):
    if is_event_checked(user_id, game, event, task, date):
        db.remove((User.user_id == user_id) &
                  (User.period == "event") &
                  (User.date == date) &
                  (User.game == game) &
                  (User.event == event) &
                  (User.task == task))
    else:
        db.insert({
            "user_id": user_id,
            "period": "event",
            "date": date,
            "game": game,
            "event": event,
            "task": task
        })

        
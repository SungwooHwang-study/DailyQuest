import os

for path in ["/data/checklist.json", "/data/users.json", "/data/quests.json"]:
    try:
        os.remove(path)
        print(f"✅ 즉시 삭제 완료: {path}")
    except Exception as e:
        print(f"⚠️ 즉시 삭제 실패: {path}: {e}")

# utils/storage.py
from tinydb import TinyDB, Query
from datetime import datetime
from utils.backup import load_or_restore_db
import os

CHECKLIST_PATH = "/data/checklist.json"

# checklist.json 복원 또는 새로 로드
db = TinyDB("/data/checklist.json")
User = Query()
modified = False

for record in db:
    task = record.get("task")
    if isinstance(task, dict) and "name" in task:
        record["task"] = task["name"]
        db.update({"task": record["task"]}, doc_ids=[record.doc_id])
        modified = True

if modified:
    print("✅ checklist.json 내부 task 필드 정규화 완료")
else:
    print("✅ checklist.json은 이미 정규화되어 있음")

def normalize_task(task):
    if isinstance(task, dict):
        return task.get("name", "UNKNOWN")
    elif isinstance(task, str):
        return task
    else:
        print(f"[경고] 알 수 없는 task 타입: {type(task)} → {task}")
        return str(task)
    
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

def is_checked(user_id, game, task_name, period="daily"):
    task_name = normalize_task(task_name)  # 혹시라도 dict로 넘어온 경우 대비
    return db.get(
        (User.user_id == user_id) &
        (User.game == game) &
        (User.task == task_name) &
        (User.period == period)
    ) is not None

def toggle_check(user_id: int, game: str, task: str, period: str = "daily"):
    if is_checked(user_id, game, task, period):
        remove_check(user_id, game, task, period)
    else:
        add_check(user_id, game, task, period)

def add_check(user_id: int, game: str, task: str, period: str = "daily"):
    key = get_today() if period == "daily" else get_week_key()
    db.insert({
        "user_id": user_id,
        "period": period,
        "date": key,
        "game": game,
        "task": task
    })

def remove_check(user_id: int, game: str, task: str, period: str = "daily"):
    key = get_today() if period == "daily" else get_week_key()
    db.remove((User.user_id == user_id) &
              (User.period == period) &
              (User.date == key) &
              (User.game == game) &
              (User.task == task))

def complete_all(user_id: int, game: str, tasks: list, period: str = "daily"):
    key = get_today() if period == "daily" else get_week_key()
    for task in tasks:
        task_name = normalize_task(task)
        if not is_checked(user_id, game, task_name, period):
            db.insert({
                "user_id": user_id,
                "period": period,
                "date": key,
                "game": game,
                "task": task_name
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

        
# utils/users.py
from datetime import datetime
from tinydb import TinyDB, Query
from utils.backup import load_or_restore_db

db = load_or_restore_db("/data/users.json")
User = Query()

def get_all_users():
    return [entry['user_id'] for entry in db.all() if 'user_id' in entry]

def add_user(user_id: int):
    if not db.search(User.user_id == user_id):
        db.insert({
            "user_id": user_id,
            "day_streak": 0,
            "last_day_complete": None
        })

def get_day_streak(user_id: int):
    result = db.search(User.user_id == user_id)
    if result and isinstance(result[0], dict):
        return result[0].get("day_streak", 0)
    return 0

def update_day_complete(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    result = db.search(User.user_id == user_id)
    if result:
        last_day = result[0].get("last_day_complete")
        if last_day == today:
            return result[0]["day_streak"]  # 이미 갱신됨

        new_streak = result[0].get("day_streak", 0) + 1
        db.update({
            "day_streak": new_streak,
            "last_day_complete": today
        }, User.user_id == user_id)
        return new_streak
    return 0

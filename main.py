import os
import json
import asyncio
import threading
import aiohttp
from aiohttp import web
from datetime import datetime, timedelta, date
from pytz import timezone
from utils.backup import rolling_backup, cleanup_old_backups, load_or_restore_db
from utils.storage import normalize_task
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from apscheduler.schedulers.background import BackgroundScheduler
from utils import users, storage  

print(timezone("Asia/Seoul"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise EnvironmentError("❌ TELEGRAM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")

SELF_URL = os.getenv("SELF_URL")

if not SELF_URL:
    print("⚠️ SELF_URL 환경변수가 설정되지 않아 슬립 방지 ping이 비활성화됩니다.")

QUESTS_PATH = "/data/quests.json"

async def handle_ping(request):
    return web.Response(text="pong")

async def start_http_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080)
    await site.start()
    print("[HTTP] Ping server running on port 8080")

async def ping_self():
    url = os.getenv("SELF_URL")  # Fly.io에 배포된 본인 주소를 환경변수로 지정
    if not url:
        print("[경고] SELF_URL 환경변수가 설정되지 않음. 슬립 방지 ping을 건너뜀.")
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                print(f"[슬립방지 ping] 상태 코드: {resp.status}")
    except Exception as e:
        print(f"[슬립방지 ping 실패] {e}")

def normalize_quests():
    global QUESTS
    modified = False
    for game, data in QUESTS.items():
        events = data.get("events", [])
        new_events = []
        for evt in events:
            evt_copy = evt.copy()
            if isinstance(evt_copy.get("tasks"), list):
                new_tasks = []
                for task in evt_copy["tasks"]:
                    if isinstance(task, str):
                        new_tasks.append({"name": task, "type": "once"})
                        modified = True
                    elif isinstance(task, dict):
                        if "name" in task:
                            if "type" not in task:
                                task["type"] = "once"
                                modified = True
                            new_tasks.append(task)
                evt_copy["tasks"] = new_tasks
            new_events.append(evt_copy)
        data["events"] = new_events

    if modified:
        with open(QUESTS_PATH, "w", encoding="utf-8") as f:
            json.dump(QUESTS, f, indent=2, ensure_ascii=False)
        print("🔧 quests.json 자동 정규화 완료됨.")
    else:
        print("✅ quests.json 정규화 불필요 — 모든 항목에 type 있음")

def load_quests():
    global QUESTS
    os.makedirs("/data", exist_ok=True)

    # quests.json 복원 또는 로드
    try:
        load_or_restore_db(QUESTS_PATH)  # 복구만 하고 반환된 TinyDB는 사용하지 않음
    except Exception as e:
        print(f"⚠️ quests.json 복구 시도 실패: {e}")
    # quests.json 로드
    try:
        with open(QUESTS_PATH, "r", encoding="utf-8") as f:
            QUESTS = json.load(f)
        if not isinstance(QUESTS, dict):
            raise ValueError("quests.json이 딕셔너리 형태가 아닙니다.")
        print("✅ quests.json 로드 성공")
    except Exception as e:
        print(f"❌ quests.json 로드 실패: {e}")
        QUESTS = {}

    normalize_quests()

# 초기화 작업: 일일 숙제 리셋
def reset_daily_tasks():
    # "daily" 기간에 해당하는 모든 기록 삭제
    storage.db.remove(storage.User.period == "daily")
    print(f"[{datetime.datetime.now()}] Daily tasks reset.")

# 초기화 작업: 주간 숙제 리셋
def reset_weekly_tasks():
    # "weekly" 기간에 해당하는 모든 기록 삭제
    storage.db.remove(storage.User.period == "weekly")
    print(f"[{datetime.datetime.now()}] Weekly tasks reset.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 이벤트 추가가 취소되었습니다.")
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"/start called by user {update.effective_user.id}")
    await update.message.reply_text("봇 살아있음!")
    user_id = update.effective_user.id
    users.add_user(user_id)
    game_list = "\n".join(f"- {game}" for game in QUESTS.keys())
    await update.message.reply_text(
        "🎮 안녕하세요! 게임 숙제 체크봇입니다.\n"
        "현재 일일 숙제 진행 중인 게임 목록:\n\n"
        f"{game_list}\n\n"
        "/daily 명령어로 오늘 숙제를 확인해보세요!"
    )

def get_week_of_month(date: datetime.date):
    first_day = date.replace(day=1)
    adjusted_dom = date.day + first_day.weekday()  # 요일 보정
    return int(adjusted_dom / 7) + 1

def build_daily_keyboard(user_id: int):
    keyboard = []

    print("[디버그] QUESTS 구조 확인")
    print(type(QUESTS))
    for game, tasks in QUESTS.items():
        print(f"  - {game}: {type(tasks)}")

    for game, tasks in QUESTS.items():
        daily_tasks = tasks.get("daily", [])
        if not daily_tasks:
            continue
        keyboard.append([InlineKeyboardButton(f"🎮 {game}", callback_data="noop")])
        row = []
        for task in daily_tasks:
            try:
                task_name = normalize_task(task)
                checked = storage.is_checked(user_id, game, task_name)
                checkmark = "✅" if checked else "☐"
                btn_text = f"{checkmark} {task_name}"
                callback_data = f"{game}|{task_name}"
                print(f"[버튼 생성] game={game}, task={task_name}, callback_data={callback_data}, type={type(task)}")
                row.append(InlineKeyboardButton(btn_text, callback_data=callback_data))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            except Exception as e:
                print(f"[버튼 생성 실패] game={game}, task={task}, 오류={e}")
        if row:
            keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


async def send_daily_to_all_users(app):
    from telegram.constants import ParseMode
    for user_id in users.get_all_users():
        try:
            reply_markup = build_daily_keyboard(user_id)
            await app.bot.send_message(
                chat_id=user_id,
                text="☀️ 새로운 하루입니다!\n오늘의 일일 숙제를 확인해보세요!",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            print(f"[ERROR] {user_id}에게 메시지 전송 실패: {e}")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.add_user(user_id)
    reply_markup = build_daily_keyboard(user_id)
    await update.message.reply_text(
        "📅 오늘의 일일 숙제 체크리스트입니다.\n숙제를 완료하면 눌러서 체크하세요!",
        reply_markup=reply_markup
    )

async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reply_markup = build_weekly_keyboard(user_id)
    await update.message.reply_text(
        "🗓️ 이번 주의 주간 숙제 체크리스트입니다.\n숙제를 완료하면 눌러서 체크하세요!",
        reply_markup=reply_markup
    )

def build_weekly_keyboard(user_id: int):
    keyboard = []
    for game, tasks in QUESTS.items():
        weekly_tasks = tasks.get("weekly", [])
        if not weekly_tasks:
            continue
        keyboard.append([InlineKeyboardButton(f"📘 {game}", callback_data="noop")])
        row = []
        for task in weekly_tasks:
            checked = storage.is_checked(user_id, game, task, period="weekly")
            checkmark = "✅" if checked else "☐"
            btn_text = f"{checkmark} {task}"
            callback_data = f"weekly|{game}|{task}"
            row.append(InlineKeyboardButton(btn_text, callback_data=callback_data))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

(ADD_GAME, ADD_PERIOD, ADD_TASKS) = range(3)
(DEL_GAME, DEL_PERIOD, DEL_TASKS) = range(3, 6)

add_data = {}
del_data = {}

async def addtask_start(update, context):
    await update.message.reply_text("📥 숙제를 추가할 게임명을 입력해주세요:")
    return ADD_GAME

async def addtask_period(update, context):
    game = update.message.text.strip()
    if game not in QUESTS:
        await update.message.reply_text("❌ 존재하지 않는 게임입니다. 다시 입력해주세요:")
        return ADD_GAME
    add_data["game"] = game
    await update.message.reply_text("📂 추가할 숙제의 유형을 선택해주세요 (daily 또는 weekly):")
    return ADD_PERIOD

async def addtask_tasks(update, context):
    period = update.message.text.strip().lower()
    if period not in ["daily", "weekly"]:
        await update.message.reply_text("❗ 유형은 daily 또는 weekly 중 하나만 입력해주세요:")
        return ADD_PERIOD
    add_data["period"] = period
    await update.message.reply_text("📝 추가할 숙제들을 쉼표로 구분하여 입력해주세요:")
    return ADD_TASKS

async def addtask_save(update, context):
    tasks = [t.strip() for t in update.message.text.split(",") if t.strip()]
    game, period = add_data["game"], add_data["period"]
    QUESTS[game].setdefault(period, []).extend(t for t in tasks if t not in QUESTS[game][period])
    with open(QUESTS_PATH, "w", encoding="utf-8") as f:
        json.dump(QUESTS, f, indent=2, ensure_ascii=False)
    await update.message.reply_text(f"✅ '{game}'의 {period} 숙제에 항목을 추가했습니다!")
    return ConversationHandler.END

async def deltask_start(update, context):
    await update.message.reply_text("📤 숙제를 삭제할 게임명을 입력해주세요:")
    return DEL_GAME

async def deltask_period(update, context):
    game = update.message.text.strip()
    if game not in QUESTS:
        await update.message.reply_text("❌ 존재하지 않는 게임입니다. 다시 입력해주세요:")
        return DEL_GAME
    del_data["game"] = game
    await update.message.reply_text("📂 삭제할 숙제의 유형을 선택해주세요 (daily 또는 weekly):")
    return DEL_PERIOD

async def deltask_tasks(update, context):
    period = update.message.text.strip().lower()
    if period not in ["daily", "weekly"]:
        await update.message.reply_text("❗ 유형은 daily 또는 weekly 중 하나만 입력해주세요:")
        return DEL_PERIOD
    del_data["period"] = period
    await update.message.reply_text("🧹 삭제할 숙제들을 쉼표로 구분하여 입력해주세요:")
    return DEL_TASKS

async def deltask_save(update, context):
    tasks = [t.strip() for t in update.message.text.split(",") if t.strip()]
    game, period = del_data["game"], del_data["period"]
    QUESTS[game][period] = [t for t in QUESTS[game].get(period, []) if t not in tasks]
    with open(QUESTS_PATH, "w", encoding="utf-8") as f:
        json.dump(QUESTS, f, indent=2, ensure_ascii=False)
    await update.message.reply_text(f"🗑️ '{game}'의 {period} 숙제에서 항목을 삭제했습니다!")
    return ConversationHandler.END

# 등록
addtask_handler = ConversationHandler(
    entry_points=[CommandHandler("addtask", addtask_start)],
    states={
        ADD_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtask_period)],
        ADD_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtask_tasks)],
        ADD_TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtask_save)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

deltask_handler = ConversationHandler(
    entry_points=[CommandHandler("deltask", deltask_start)],
    states={
        DEL_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, deltask_period)],
        DEL_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, deltask_tasks)],
        DEL_TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, deltask_save)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if query.data == "noop":
        return

    if query.data.startswith("weekly|"):
        _, game, task = query.data.split("|")
        storage.toggle_check(user_id, game, task, period="weekly")
        reply_markup = build_weekly_keyboard(user_id)
    elif query.data.startswith("event|"):
        # 이벤트 콜백 데이터 형식: "event|game|evt_name|task|date_key"
        parts = query.data.split("|")
        if len(parts) == 5:
            _, game, evt_name, task, date_key = parts
            storage.toggle_event_check(user_id, game, evt_name, task, date_key)
            reply_markup = build_event_keyboard(user_id)
        else:
            reply_markup = None
    else:
        try:
            game, task = query.data.split("|")
        except ValueError:
            return
        storage.toggle_check(user_id, game, task, period="daily")
        reply_markup = build_daily_keyboard(user_id)

    if reply_markup is not None:
        await query.edit_message_reply_markup(reply_markup=reply_markup)

async def complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.add_user(user_id)
    
    if not context.args:
        await update.message.reply_text("❗ 사용법: /complete [게임명] [weekly(optional)]")
        return

    # 주간 여부 확인
    if context.args[-1].lower() == "weekly":
        game = " ".join(context.args[:-1])
        period = "weekly"
    else:
        game = " ".join(context.args)
        period = "daily"

    if game not in QUESTS:
        await update.message.reply_text(f"❌ 존재하지 않는 게임입니다: {game}")
        return

    task_list = QUESTS[game].get(period, [])
    if not task_list:
        await update.message.reply_text(f"📭 '{game}'에는 {period} 숙제가 없습니다.")
        return

    storage.complete_all(user_id, game, task_list, period=period)
    await update.message.reply_text(f"✅ '{game}'의 {period} 숙제를 모두 완료 처리했습니다!")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.add_user(user_id)
    today = date.today()
    all_completed = True

    for game, data in QUESTS.items():
        # 일반 daily 숙제만 확인 (이벤트는 이미 daily에 병합됨)
        for task in data.get("daily", []):
            if not storage.is_checked(user_id, game, task, period="daily"):
                all_completed = False
                break
        if not all_completed:
            break

    if all_completed:
        day_n = users.update_day_complete(user_id)
        await update.message.reply_text(f"🎉 오늘의 숙제를 모두 완료했습니다!\n🔥 Day {day_n} 클리어!")
    else:
        await update.message.reply_text("🧐 아직 완료되지 않은 숙제가 있어요.\n이벤트 숙제도 포함해서 모두 완료해야 Day 카운트가 올라가요!")

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.add_user(user_id)
    msg = "📊 오늘의 진행 상황\n"
    for game, tasks in QUESTS.items():
        daily_tasks = tasks.get("daily", [])
        if not daily_tasks:
            continue
        total = len(daily_tasks)
        completed = sum(1 for task in daily_tasks if storage.is_checked(user_id, game, task, period="daily"))
        checkmark = " ✅" if completed == total else ""
        msg += f"\n🎮 {game}: {completed} / {total} 완료{checkmark}"
    await update.message.reply_text(msg)

async def event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.add_user(user_id)
    today = date.today()
    keyboard = []
    for game, data in QUESTS.items():
        events = data.get("events", [])
        for evt in events:
            evt_name = evt["name"]
            evt_type = evt.get("type", "once")
            until = date.fromisoformat(evt["until"])
            if today > until:
                continue  # 종료된 이벤트
            date_key = today.strftime("%Y-%m-%d") if evt_type == "daily" else evt["until"]
            keyboard.append([InlineKeyboardButton(f"🎉 {game} - {evt_name}", callback_data="noop")])
            row = []
            for task in evt["tasks"]:
                checked = storage.is_event_checked(user_id, game, evt_name, task["name"], date_key)
                mark = "✅" if checked else "☐"
                callback_data = f"event|{game}|{evt_name}|{task['name']}|{date_key}"
                row.append(InlineKeyboardButton(f"{mark} {task['name']}", callback_data=callback_data))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
    if not keyboard:
        await update.message.reply_text("📭 현재 진행 중인 이벤트가 없습니다.")
        return
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 진행 중인 이벤트 목록입니다!", reply_markup=reply_markup)

def build_event_keyboard(user_id: int):
    # 이벤트 목록을 다시 빌드하는 함수
    keyboard = []
    today = date.today()
    for game, data in QUESTS.items():
        events = data.get("events", [])
        for evt in events:
            evt_name = evt["name"]
            evt_type = evt.get("type", "once")
            until = date.fromisoformat(evt["until"])
            if today > until:
                continue
            date_key = today.strftime("%Y-%m-%d") if evt_type == "daily" else evt["until"]
            keyboard.append([InlineKeyboardButton(f"🎉 {game} - {evt_name}", callback_data="noop")])
            row = []
            for task in evt["tasks"]:
                checked = storage.is_event_checked(user_id, game, evt_name, task["name"], date_key)
                mark = "✅" if checked else "☐"
                callback_data = f"event|{game}|{evt_name}|{task['name']}|{date_key}"
                row.append(InlineKeyboardButton(f"{mark} {task['name']}", callback_data=callback_data))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

(ASK_GAME, ASK_EVENT_NAME, ASK_UNTIL, ASK_TASK_NAME, ASK_TASK_TYPE, ASK_MORE_TASKS) = range(6)
event_data = {}

async def addevent_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 이벤트를 추가할 게임명을 입력해주세요:")
    return ASK_GAME

async def ask_event_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = update.message.text
    if game not in QUESTS:
        await update.message.reply_text("❌ 존재하지 않는 게임입니다. 다시 입력해주세요:")
        return ASK_GAME
    event_data.clear()
    event_data["game"] = game
    await update.message.reply_text("📛 이벤트 이름을 입력해주세요:")
    return ASK_EVENT_NAME

async def ask_until(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_data["name"] = update.message.text
    await update.message.reply_text("📅 이벤트 종료일을 입력해주세요 (예: 2025-04-15):")
    return ASK_UNTIL

async def ask_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        until_date = datetime.fromisoformat(update.message.text).date()
        event_data["until"] = str(until_date)
        event_data["tasks"] = []
    except:
        await update.message.reply_text("❗날짜 형식이 올바르지 않아요. 예: 2025-04-15")
        return ASK_UNTIL
    await update.message.reply_text("📝 숙제명을 입력해주세요:")
    return ASK_TASK_NAME

async def ask_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_data["current_task"] = update.message.text.strip()
    await update.message.reply_text("📂 숙제 타입을 선택해주세요 (daily / once):")
    return ASK_TASK_TYPE

async def ask_more_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_type = update.message.text.strip().lower()
    if task_type not in ["daily", "once"]:
        await update.message.reply_text("❌ daily 또는 once 중에 선택해주세요:")
        return ASK_TASK_TYPE
    event_data["tasks"].append({
        "name": event_data["current_task"],
        "type": task_type
    })
    await update.message.reply_text("➕ 숙제를 더 추가하시겠습니까? (예/아니오):")
    return ASK_MORE_TASKS

async def save_event_or_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().lower()
    if answer in ["아니오", "n", "no"]:
        game = event_data["game"]
        new_event = {
            "name": event_data["name"],
            "until": event_data["until"],
            "tasks": event_data["tasks"]
        }
        QUESTS[game].setdefault("events", []).append(new_event)
        with open(QUESTS_PATH, "w", encoding="utf-8") as f:
            json.dump(QUESTS, f, indent=2, ensure_ascii=False)
        await update.message.reply_text(f"✅ 이벤트가 추가되었습니다!\n📌 {event_data['name']} ({len(event_data['tasks'])}개 숙제)")
        return ConversationHandler.END
    else:
        await update.message.reply_text("📝 다음 숙제명을 입력해주세요:")
        return ASK_TASK_NAME
    
addevent_handler = ConversationHandler(
    entry_points=[CommandHandler("addevent", addevent_start)],
    states={
        ASK_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_event_name)],
        ASK_EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_until)],
        ASK_UNTIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_task_name)],
        ASK_TASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_task_type)],
        ASK_TASK_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_more_tasks)],
        ASK_MORE_TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_event_or_continue)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

(RENAME_OLD_NAME, RENAME_NEW_NAME) = range(10, 12)
rename_data = {}

async def renamegame_start(update, context):
    await update.message.reply_text("✏️ 변경할 기존 게임명을 입력해주세요:")
    return RENAME_OLD_NAME

async def renamegame_new(update, context):
    old_name = update.message.text.strip()
    if old_name not in QUESTS:
        await update.message.reply_text("❌ 해당 게임이 존재하지 않습니다. 다시 입력해주세요:")
        return RENAME_OLD_NAME
    rename_data["old"] = old_name
    await update.message.reply_text("📛 새 게임명을 입력해주세요:")
    return RENAME_NEW_NAME

async def renamegame_apply(update, context):
    new_name = update.message.text.strip()
    old_name = rename_data["old"]
    QUESTS[new_name] = QUESTS.pop(old_name)
    with open(QUESTS_PATH, "w", encoding="utf-8") as f:
        json.dump(QUESTS, f, indent=2, ensure_ascii=False)
    await update.message.reply_text(f"✅ '{old_name}' → '{new_name}' 로 이름이 변경되었습니다.")
    return ConversationHandler.END

(EDIT_GAME, EDIT_PERIOD, EDIT_OLD_TASK, EDIT_NEW_TASK) = range(20, 24)
edit_data = {}

async def editquest_start(update, context):
    await update.message.reply_text("🛠 수정할 게임명을 입력해주세요:")
    return EDIT_GAME

async def editquest_period(update, context):
    game = update.message.text.strip()
    if game not in QUESTS:
        await update.message.reply_text("❌ 해당 게임이 존재하지 않습니다. 다시 입력해주세요:")
        return EDIT_GAME
    edit_data["game"] = game
    await update.message.reply_text("📂 수정할 숙제 유형을 입력해주세요 (daily / weekly):")
    return EDIT_PERIOD

async def editquest_old(update, context):
    period = update.message.text.strip().lower()
    if period not in ["daily", "weekly"]:
        await update.message.reply_text("❗ daily 또는 weekly 중에서 입력해주세요:")
        return EDIT_PERIOD
    edit_data["period"] = period
    await update.message.reply_text("✏️ 수정할 기존 숙제명을 입력해주세요:")
    return EDIT_OLD_TASK

async def editquest_new(update, context):
    old_task = update.message.text.strip()
    game, period = edit_data["game"], edit_data["period"]
    if old_task not in QUESTS[game].get(period, []):
        await update.message.reply_text("❌ 해당 숙제가 존재하지 않습니다. 다시 입력해주세요:")
        return EDIT_OLD_TASK
    edit_data["old"] = old_task
    await update.message.reply_text("🆕 새 숙제명을 입력해주세요:")
    return EDIT_NEW_TASK

async def editquest_apply(update, context):
    new_task = update.message.text.strip()
    game, period, old = edit_data["game"], edit_data["period"], edit_data["old"]
    tasks = QUESTS[game][period]
    QUESTS[game][period] = [new_task if t == old else t for t in tasks]
    with open(QUESTS_PATH, "w", encoding="utf-8") as f:
        json.dump(QUESTS, f, indent=2, ensure_ascii=False)
    await update.message.reply_text(f"✅ '{old}' → '{new_task}' 로 숙제명이 수정되었습니다!")
    return ConversationHandler.END

renamegame_handler = ConversationHandler(
    entry_points=[CommandHandler("renamegame", renamegame_start)],
    states={
        RENAME_OLD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, renamegame_new)],
        RENAME_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, renamegame_apply)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

editquest_handler = ConversationHandler(
    entry_points=[CommandHandler("editquest", editquest_start)],
    states={
        EDIT_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, editquest_period)],
        EDIT_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, editquest_old)],
        EDIT_OLD_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, editquest_new)],
        EDIT_NEW_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, editquest_apply)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# 이벤트 만료 후 제거 + daily type은 daily에 반영 (단 제거는 하지 않음)
def refresh_event_tasks():
    today = date.today()
    modified = False
    for game, data in QUESTS.items():
        events = data.get("events", [])
        new_events = []
        daily_from_events = set(data.get("daily", []))  # 기존 daily 숙제들

        for evt in events:
            until = datetime.fromisoformat(evt["until"]).date()
            if today > until:
                modified = True  # 만료된 이벤트는 제거
                continue

            for task in evt.get("tasks", []):
                if task["type"] == "daily":
                    task_name = task["name"]
                    if task_name not in daily_from_events:
                        daily_from_events.add(task_name)
                        modified = True
            new_events.append(evt)

        # 중복 없이 업데이트
        original_daily = set(data.get("daily", []))
        data["daily"] = list(original_daily.union(daily_from_events))

    if modified:
        with open(QUESTS_PATH, "w", encoding="utf-8") as f:
            json.dump(QUESTS, f, indent=2, ensure_ascii=False)
        print("✅ daily 이벤트 반영 및 만료 제거 완료")
    else:
        print("✅ 업데이트 필요 없음")

# 이벤트 알림용 함수
async def notify_once_event_tasks(app):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    for user_id in users.get_all_users():
        try:
            msg = "📢 내일 마감되는 one-time 이벤트 숙제가 있어요!\n"
            found = False
            for game, data in QUESTS.items():
                for evt in data.get("events", []):
                    until = datetime.fromisoformat(evt["until"]).date()
                    if until == tomorrow:
                        once_tasks = [t["name"] for t in evt.get("tasks", []) if t["type"] == "once"]
                        if once_tasks:
                            found = True
                            msg += f"\n🎮 {game} - {evt['name']}\n- " + "\n- ".join(once_tasks)
            if found:
                await app.bot.send_message(chat_id=user_id, text=msg)
        except Exception as e:
            print(f"[ERROR] {user_id}에게 one-time 알림 실패: {e}")

# 이벤트 삭제 핸들러
(DEL_EVT_GAME, DEL_EVT_NAME) = range(30, 32)
del_event_data = {}

async def delevent_start(update, context):
    await update.message.reply_text("🗑️ 삭제할 이벤트의 게임명을 입력해주세요:")
    return DEL_EVT_GAME

async def delevent_name(update, context):
    game = update.message.text.strip()
    if game not in QUESTS or not QUESTS[game].get("events"):
        await update.message.reply_text("❌ 이벤트가 존재하지 않는 게임입니다.")
        return ConversationHandler.END
    del_event_data["game"] = game
    event_names = [evt["name"] for evt in QUESTS[game]["events"]]
    await update.message.reply_text(f"🔍 삭제할 이벤트 이름을 입력해주세요:\n현재 이벤트: {', '.join(event_names)}")
    return DEL_EVT_NAME

async def delevent_confirm(update, context):
    evt_name = update.message.text.strip()
    game = del_event_data["game"]
    before_count = len(QUESTS[game]["events"])
    QUESTS[game]["events"] = [evt for evt in QUESTS[game]["events"] if evt["name"] != evt_name]
    after_count = len(QUESTS[game]["events"])
    if before_count == after_count:
        await update.message.reply_text("❗ 해당 이벤트를 찾을 수 없습니다.")
    else:
        with open(QUESTS_PATH, "w", encoding="utf-8") as f:
            json.dump(QUESTS, f, indent=2, ensure_ascii=False)
        await update.message.reply_text(f"✅ '{evt_name}' 이벤트가 삭제되었습니다.")
    return ConversationHandler.END

delevent_handler = ConversationHandler(
    entry_points=[CommandHandler("delevent", delevent_start)],
    states={
        DEL_EVT_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, delevent_name)],
        DEL_EVT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, delevent_confirm)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# 이벤트 수정 핸들러
(EDIT_EVT_GAME, EDIT_EVT_NAME, EDIT_EVT_OLD_TASK, EDIT_EVT_NEW_TASK) = range(40, 44)
edit_event_data = {}

async def editevent_start(update, context):
    await update.message.reply_text("🛠 이벤트 숙제를 수정할 게임명을 입력해주세요:")
    return EDIT_EVT_GAME

async def editevent_name(update, context):
    game = update.message.text.strip()
    if game not in QUESTS or not QUESTS[game].get("events"):
        await update.message.reply_text("❌ 이벤트가 존재하지 않는 게임입니다.")
        return ConversationHandler.END
    edit_event_data["game"] = game
    event_names = [evt["name"] for evt in QUESTS[game]["events"]]
    await update.message.reply_text(f"📝 이벤트 이름을 입력해주세요:\n{', '.join(event_names)}")
    return EDIT_EVT_NAME

async def editevent_old_task(update, context):
    name = update.message.text.strip()
    game = edit_event_data["game"]
    evt = next((e for e in QUESTS[game]["events"] if e["name"] == name), None)
    if not evt:
        await update.message.reply_text("❌ 이벤트를 찾을 수 없습니다.")
        return ConversationHandler.END
    edit_event_data["name"] = name
    task_names = [t["name"] for t in evt["tasks"]]
    await update.message.reply_text(f"✏️ 수정할 숙제명을 입력해주세요:\n{', '.join(task_names)}")
    return EDIT_EVT_OLD_TASK

async def editevent_new_task(update, context):
    old_task = update.message.text.strip()
    game, name = edit_event_data["game"], edit_event_data["name"]
    evt = next((e for e in QUESTS[game]["events"] if e["name"] == name), None)
    task = next((t for t in evt["tasks"] if t["name"] == old_task), None)
    if not task:
        await update.message.reply_text("❌ 해당 숙제가 없습니다.")
        return ConversationHandler.END
    edit_event_data["old_task"] = task
    await update.message.reply_text("🆕 새 숙제명을 입력해주세요:")
    return EDIT_EVT_NEW_TASK

async def editevent_apply(update, context):
    new_name = update.message.text.strip()
    edit_event_data["old_task"]["name"] = new_name
    with open(QUESTS_PATH, "w", encoding="utf-8") as f:
        json.dump(QUESTS, f, indent=2, ensure_ascii=False)
    await update.message.reply_text("✅ 숙제명이 수정되었습니다.")
    return ConversationHandler.END

editevent_handler = ConversationHandler(
    entry_points=[CommandHandler("editevent", editevent_start)],
    states={
        EDIT_EVT_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, editevent_name)],
        EDIT_EVT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, editevent_old_task)],
        EDIT_EVT_OLD_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, editevent_new_task)],
        EDIT_EVT_NEW_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, editevent_apply)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# 숙제 목록 출력
async def listtasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    msg = "📋 현재 등록된 숙제 목록입니다:\n"

    # 기본 숙제 출력
    for game, tasks in QUESTS.items():
        msg += f"\n🎮 {game}\n"
        daily = tasks.get("daily", [])
        weekly = tasks.get("weekly", [])
        if daily:
            msg += f"- Daily: {', '.join(daily)}\n"
        if weekly:
            msg += f"- Weekly: {', '.join(weekly)}\n"

    # 이벤트 D-DAY 정렬 후 출력
    event_lines = []
    for game, data in QUESTS.items():
        for evt in data.get("events", []):
            until = datetime.fromisoformat(evt["until"]).date()
            dday = (until - today).days
            dday_text = f"D-{dday}" if dday >= 0 else f"D+{abs(dday)}"
            line = f"[ {dday_text} ] {game} - {evt['name']}\n"
            for task in evt["tasks"]:
                line += f"  • [{task['type']}] {task['name']}\n"
            event_lines.append((dday, line))

    if event_lines:
        msg += "\n📅 진행 중인 이벤트:\n"
        for _, line in sorted(event_lines, key=lambda x: x[0]):
            msg += line

    await update.message.reply_text(msg)

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    refresh_event_tasks()
    await update.message.reply_text("📨 테스트 알림을 전송합니다.")
    await send_daily_to_all_users(context.application)

# 백업 함수

def backup_quests():
    try:
        rolling_backup("/data/quests.json")
        cleanup_old_backups("/data")
        print("📦 quests.json 백업 완료")
    except Exception as e:
        print(f"[백업 실패] {e}")

def backup_checklist():
    try:
        rolling_backup("/data/checklist.json")
        cleanup_old_backups("/data")
        print("📦 checklist.json 백업 완료")
    except Exception as e:
        print(f"[checklist 백업 실패] {e}")

def backup_users():
    try:
        rolling_backup("/data/users.json")
        cleanup_old_backups("/data")
        print("📦 users.json 백업 완료")
    except Exception as e:
        print(f"[users 백업 실패] {e}")

# help 명령어
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🧾 *사용 가능한 명령어 목록:*\n\n"
        "📌 _기본 기능_\n"
        "/start - 봇 시작 및 인사\n"
        "/daily - 오늘의 일일 숙제 확인\n"
        "/weekly - 이번 주의 주간 숙제 확인\n"
        "/complete [게임명] [weekly(optional)] - 게임 숙제 일괄 완료 처리\n"
        "/done - 모든 일일 숙제 완료 시 Day 클리어 처리\n"
        "/progress - 오늘의 숙제 진행 상황 확인\n"
        "/listtasks - 전체 게임 및 이벤트 숙제 보기 (D-Day 정렬 포함)\n\n"
        "📆 _이벤트 관련_\n"
        "/addevent - 이벤트 추가 (대화형)\n"
        "/event - 진행 중인 이벤트 목록 보기\n"
        "/delevent - 이벤트 삭제 (입력형)\n"
        "/editevent - 이벤트 숙제 이름 수정\n\n"
        "🛠 _숙제/게임 관리_\n"
        "/addtask - 숙제 항목 추가 (입력형)\n"
        "/deltask - 숙제 항목 삭제 (입력형)\n"
        "/renamegame - 게임 이름 변경\n"
        "/editquest - 숙제 이름 수정 (입력형)\n\n"
        "/importquests - 로컬의 quests.json 파일을 첨부해 업로드\n"
        "❓ /help - 이 도움말 보기"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def import_quests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("📎 *quests.json* 파일을 첨부해서 `/importquests` 명령어로 보내주세요.", parse_mode=ParseMode.MARKDOWN)
        return

    file = await context.bot.get_file(update.message.document.file_id)
    file_path = "/data/quests.json"
    try:
        await file.download_to_drive(file_path)
        await update.message.reply_text("✅ *quests.json*이 성공적으로 덮어씌워졌습니다!", parse_mode=ParseMode.MARKDOWN)
        # 새로 불러오기
        load_quests()
    except Exception as e:
        await update.message.reply_text(f"❌ 파일 저장 실패: {e}")

loop = asyncio.new_event_loop()

def safe_run(coro):
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    def handle_exception(f):
        exception = f.exception()
        if exception:
            print("[스케줄러 예외]", exception)

    future.add_done_callback(handle_exception)
    return future

def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def main():
    load_quests()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 핸들러 등록
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("weekly", weekly))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("complete", complete))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("progress", progress))
    app.add_handler(CommandHandler("event", event))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("test", test_notify))
    app.add_handler(CommandHandler("listtasks", listtasks))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.CaptionRegex(r"^/importquests$"), import_quests))
    app.add_handler(renamegame_handler)
    app.add_handler(editquest_handler)
    app.add_handler(addtask_handler)
    app.add_handler(deltask_handler)
    app.add_handler(addevent_handler)
    app.add_handler(delevent_handler)
    app.add_handler(editevent_handler)

    # 전용 이벤트 루프 생성 후 별도 스레드에서 실행
    t = threading.Thread(target=start_loop, args=(loop,), daemon=True)
    t.start()

    # HTTP 서버도 이벤트 루프에서 함께 실행
    safe_run(start_http_server())

    # BackgroundScheduler 사용
    scheduler = BackgroundScheduler()

    # 매일 오전 8시 알림 전송 (KST)
    scheduler.add_job(
        lambda: safe_run(send_daily_to_all_users(app)),
        trigger="cron",
        hour=8,
        minute=0,
        timezone=timezone("Asia/Seoul")
    )

    # 매일 오전 5시 일일 숙제 초기화
    scheduler.add_job(reset_daily_tasks, trigger="cron", hour=5, minute=0, timezone=timezone("Asia/Seoul"))
    # 매주 월요일 오전 5시 주간 숙제 초기화
    scheduler.add_job(reset_weekly_tasks, trigger="cron", day_of_week="mon", hour=5, minute=0, timezone=timezone("Asia/Seoul"))
    # 10분 주기 슬립 방지 ping
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(ping_self(), loop), trigger="interval",minutes=10)
    # 이벤트 만료 및 daily 이벤트 반영
    scheduler.add_job(lambda: safe_run(notify_once_event_tasks(app)), trigger="cron", hour=8, minute=0, timezone=timezone("Asia/Seoul"))
    scheduler.add_job(refresh_event_tasks, trigger="cron", hour=5, minute=0, timezone=timezone("Asia/Seoul"))

    # 매일 오전 5시 quests.json 백업
    scheduler.add_job(backup_quests, trigger="cron", hour=5, minute=0, timezone=timezone("Asia/Seoul"))

    # 매일 오전 5시 checklist.json 백업
    scheduler.add_job(backup_checklist, trigger="cron", hour=5, minute=0, timezone=timezone("Asia/Seoul"))

    # 매일 오전 5시 users.json 백업
    scheduler.add_job(backup_users, trigger="cron", hour=5, minute=0, timezone=timezone("Asia/Seoul"))


    scheduler.start()

    print("Bot is running with scheduler...")
    app.run_polling()

if __name__ == "__main__":
    main()

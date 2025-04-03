import os
import json
import datetime
import asyncio
import threading
import aiohttp
from aiohttp import web
from pytz import timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from utils import users, storage  

print(timezone("Asia/Seoul"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QUESTS = {}

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

def load_quests():
    global QUESTS
    with open("data/quests.json", "r", encoding="utf-8") as f:
        QUESTS = json.load(f)

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
    for game, tasks in QUESTS.items():
        daily_tasks = tasks.get("daily", [])
        if not daily_tasks:
            continue
        keyboard.append([InlineKeyboardButton(f"🎮 {game}", callback_data="noop")])
        row = []
        for task in daily_tasks:
            checked = storage.is_checked(user_id, game, task)
            checkmark = "✅" if checked else "☐"
            btn_text = f"{checkmark} {task}"
            callback_data = f"{game}|{task}"
            row.append(InlineKeyboardButton(btn_text, callback_data=callback_data))
            if len(row) == 2:
                keyboard.append(row)
                row = []
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
    game = context.args[0]
    period = "weekly" if len(context.args) > 1 and context.args[1].lower() == "weekly" else "daily"
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
    all_completed = True
    for game, tasks in QUESTS.items():
        daily_tasks = tasks.get("daily", [])
        for task in daily_tasks:
            if not storage.is_checked(user_id, game, task, period="daily"):
                all_completed = False
                break
        if not all_completed:
            break
    if all_completed:
        day_n = users.update_day_complete(user_id)
        await update.message.reply_text(f"🎉 오늘의 숙제를 모두 완료했습니다!\n🔥 Day {day_n} 클리어!")
    else:
        await update.message.reply_text("🧐 아직 완료되지 않은 숙제가 있어요.\n하나라도 빠지면 Day 카운트가 올라가지 않아요!")

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
    today = datetime.date.today()
    keyboard = []
    for game, data in QUESTS.items():
        events = data.get("events", [])
        for evt in events:
            evt_name = evt["name"]
            evt_type = evt["type"]
            until = datetime.date.fromisoformat(evt["until"])
            if today > until:
                continue  # 종료된 이벤트
            date_key = today.strftime("%Y-%m-%d") if evt_type == "daily" else evt["until"]
            keyboard.append([InlineKeyboardButton(f"🎉 {game} - {evt_name}", callback_data="noop")])
            row = []
            for task in evt["tasks"]:
                checked = storage.is_event_checked(user_id, game, evt_name, task, date_key)
                mark = "✅" if checked else "☐"
                callback_data = f"event|{game}|{evt_name}|{task}|{date_key}"
                row.append(InlineKeyboardButton(f"{mark} {task}", callback_data=callback_data))
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
    today = datetime.date.today()
    for game, data in QUESTS.items():
        events = data.get("events", [])
        for evt in events:
            evt_name = evt["name"]
            evt_type = evt["type"]
            until = datetime.date.fromisoformat(evt["until"])
            if today > until:
                continue
            date_key = today.strftime("%Y-%m-%d") if evt_type == "daily" else evt["until"]
            keyboard.append([InlineKeyboardButton(f"🎉 {game} - {evt_name}", callback_data="noop")])
            row = []
            for task in evt["tasks"]:
                checked = storage.is_event_checked(user_id, game, evt_name, task, date_key)
                mark = "✅" if checked else "☐"
                callback_data = f"event|{game}|{evt_name}|{task}|{date_key}"
                row.append(InlineKeyboardButton(f"{mark} {task}", callback_data=callback_data))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

from telegram.ext import ConversationHandler
(ASK_GAME, ASK_EVENT_NAME, ASK_UNTIL, ASK_TYPE, ASK_TASKS) = range(5)
event_data = {}

async def addevent_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 이벤트를 추가할 게임명을 입력해주세요:")
    return ASK_GAME

async def ask_event_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = update.message.text
    if game not in QUESTS:
        await update.message.reply_text("❌ 존재하지 않는 게임입니다. 다시 입력해주세요:")
        return ASK_GAME
    event_data["game"] = game
    await update.message.reply_text("📛 이벤트 이름을 입력해주세요:")
    return ASK_EVENT_NAME

async def ask_until(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_data["name"] = update.message.text
    await update.message.reply_text("📅 이벤트 종료일을 입력해주세요 (예: 2025-04-15):")
    return ASK_UNTIL

async def ask_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        date = datetime.date.fromisoformat(update.message.text)
        event_data["until"] = str(date)
    except:
        await update.message.reply_text("❗날짜 형식이 올바르지 않아요. 예: 2025-04-15")
        return ASK_UNTIL
    await update.message.reply_text("📂 이벤트 타입을 입력해주세요 (daily / once):")
    return ASK_TYPE

async def ask_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    type_text = update.message.text.lower()
    if type_text not in ["daily", "once"]:
        await update.message.reply_text("❌ daily 또는 once 중에 선택해주세요.")
        return ASK_TYPE
    event_data["type"] = type_text
    await update.message.reply_text("📝 숙제들을 쉼표(,)로 구분해서 입력해주세요:\n예: 아이템 수집, 보스 처치")
    return ASK_TASKS

async def save_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = [t.strip() for t in update.message.text.split(",") if t.strip()]
    event_data["tasks"] = tasks
    game = event_data["game"]
    new_event = {
        "name": event_data["name"],
        "type": event_data["type"],
        "until": event_data["until"],
        "tasks": event_data["tasks"]
    }
    QUESTS[game].setdefault("events", []).append(new_event)
    with open("data/quests.json", "w", encoding="utf-8") as f:
        json.dump(QUESTS, f, indent=2, ensure_ascii=False)
    await update.message.reply_text(f"✅ 이벤트가 추가되었습니다!\n📌 {event_data['name']} ({event_data['type']})")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 이벤트 추가가 취소되었습니다.")
    return ConversationHandler.END

from telegram.ext import MessageHandler, filters
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("addevent", addevent_start)],
    states={
        ASK_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_event_name)],
        ASK_EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_until)],
        ASK_UNTIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_type)],
        ASK_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_tasks)],
        ASK_TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_event)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("📨 테스트 알림을 전송합니다.")
    await send_daily_to_all_users(context.application)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "사용 가능한 명령어 목록:\n"
        "/start - 봇 시작 및 인사\n"
        "/daily - 오늘의 일일 숙제 확인\n"
        "/weekly - 이번 주의 주간 숙제 확인\n"
        "/complete [게임명] [weekly(optional)] - 게임 숙제 일괄 완료 처리\n"
        "/done - 모든 일일 숙제 완료 시 Day 클리어 처리\n"
        "/progress - 오늘의 숙제 진행 상황 확인\n"
        "/addevent - 대화형으로 이벤트 추가\n"
        "/event - 진행 중인 이벤트 목록 확인\n"
        "/help - 이 도움말 메시지 보기\n"
    )
    await update.message.reply_text(help_text)

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
    app.add_handler(conv_handler)

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
    scheduler.add_job(
    lambda: asyncio.run_coroutine_threadsafe(ping_self(), loop),
    trigger="interval",
    minutes=10)

    scheduler.start()

    print("Bot is running with scheduler...")
    app.run_polling()

if __name__ == "__main__":
    main()

# main.py
import os
import json
import datetime
import asyncio
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from utils import users, storage  

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QUESTS = {}

def load_quests():
    global QUESTS
    with open("data/quests.json", "r", encoding="utf-8") as f:
        QUESTS = json.load(f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    users.add_user(user_id)  # 유저 등록
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

    # 형식 분기: daily는 "게임|숙제", weekly는 "weekly|게임|숙제"
    if query.data.startswith("weekly|"):
        _, game, task = query.data.split("|")
        storage.toggle_check(user_id, game, task, period="weekly")
        reply_markup = build_weekly_keyboard(user_id)
    else:
        game, task = query.data.split("|")
        storage.toggle_check(user_id, game, task, period="daily")
        reply_markup = build_daily_keyboard(user_id)

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

# main.py에 추가
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
        completed = sum(
            1 for task in daily_tasks
            if storage.is_checked(user_id, game, task, period="daily")
        )

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
                continue  # 이벤트 종료됨

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

    # 실제로 quests.json 수정
    game = event_data["game"]
    new_event = {
        "name": event_data["name"],
        "type": event_data["type"],
        "until": event_data["until"],
        "tasks": event_data["tasks"]
    }

    QUESTS[game].setdefault("events", []).append(new_event)

    # 저장
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
    app.add_handler(conv_handler)

    # 전용 이벤트 루프 생성 후 별도 스레드에서 실행
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=start_loop, args=(loop,), daemon=True)
    t.start()

    # BackgroundScheduler 사용: 백그라운드 스케줄러는 자체 스레드에서 실행됩니다.
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(send_daily_to_all_users(app), loop),
        trigger="cron", hour=8, minute=0
    )
    scheduler.start()

    print("Bot is running with scheduler...")
    app.run_polling()

if __name__ == "__main__":
    main()
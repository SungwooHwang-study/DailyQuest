# main.py (수정됨)
import os
import json
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from utils import users, storage  

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QUESTS = {}

def load_quests():
    global QUESTS
    with open("data/quests.json", "r", encoding="utf-8") as f:
        QUESTS = json.load(f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


    # 스케줄러 설정
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_to_all_users, trigger="cron", hour=8, minute=0, args=[app])
    scheduler.start()

    print("Bot is running with scheduler...")
    app.run_polling()
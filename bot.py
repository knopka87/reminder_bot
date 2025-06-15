# Reminder Telegram Bot with buttons, repeat options, and delay choices
# Works with python-telegram-bot v20+

import logging
from datetime import datetime, timedelta, time
import pytz
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CallbackContext, CommandHandler,
                          CallbackQueryHandler, MessageHandler, filters, ConversationHandler)

import sqlite3
import asyncio

# =============== CONFIGURATION ===============
TOKEN = os.environ.get("TOKEN")
TIMEZONE = pytz.timezone("Europe/Moscow")

# =============== DATABASE ===============
conn = sqlite3.connect("reminders.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS reminders
             (user_id INTEGER, text TEXT, time TEXT, repeat TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT)''')
conn.commit()

# =============== LOGGER ===============
logging.basicConfig(level=logging.INFO)

# =============== STATES ===============
TEXT, TYPE, TIME = range(3)

# =============== REMINDER CREATION ===============
user_data_temp = {}

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Привет! Я бот-напоминалка. Используй /new для создания напоминания.")

async def new_reminder(update: Update, context: CallbackContext):
    await update.message.reply_text("Введите текст напоминания:")
    return TEXT

async def get_text(update: Update, context: CallbackContext):
    user_data_temp[update.effective_user.id] = {"text": update.message.text}
    keyboard = [[InlineKeyboardButton("Разовое", callback_data="once"),
                 InlineKeyboardButton("Еженедельно", callback_data="weekly"),
                 InlineKeyboardButton("Ежемесячно", callback_data="monthly")]]
    await update.message.reply_text("Выберите тип напоминания:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return TYPE

async def get_type(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user_data_temp[query.from_user.id]["repeat"] = query.data
    await query.edit_message_text("Введите дату и время в формате: ДД.ММ.ГГГГ ЧЧ:ММ")
    return TIME

async def get_time(update: Update, context: CallbackContext):
    try:
        dt = datetime.strptime(update.message.text, "%d.%m.%Y %H:%M")
        dt = TIMEZONE.localize(dt)
        data = user_data_temp[update.effective_user.id]
        c.execute("INSERT INTO reminders (user_id, text, time, repeat) VALUES (?, ?, ?, ?)",
                  (update.effective_user.id, data["text"], dt.isoformat(), data["repeat"]))
        conn.commit()
        await update.message.reply_text("Напоминание добавлено!")
    except Exception as e:
        await update.message.reply_text("Ошибка! Попробуйте снова с /new")
        logging.error(str(e))
    return ConversationHandler.END

# =============== LIST & DELETE ===============
async def list_reminders(update: Update, context: CallbackContext):
    c.execute("SELECT id, text, time, repeat FROM reminders WHERE user_id = ?", (update.effective_user.id,))
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text("У вас нет активных напоминаний.")
    else:
        msg = "Ваши напоминания:\n"
        for r in rows:
            local_time = datetime.fromisoformat(r[2]).astimezone(TIMEZONE)
            msg += f"\n#{r[0]}: {r[1]} — {local_time.strftime('%d.%m.%Y %H:%M')} ({r[3]})"
        await update.message.reply_text(msg)

async def delete_reminder(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        await update.message.reply_text("Используйте: /delete <id>")
        return
    try:
        rid = int(context.args[0])
        c.execute("DELETE FROM reminders WHERE user_id = ? AND id = ?", (update.effective_user.id, rid))
        conn.commit()
        await update.message.reply_text("Удалено.")
    except:
        await update.message.reply_text("Ошибка при удалении. Убедитесь, что ID указан верно.")

# =============== REMINDER CHECK LOOP ===============
async def reminder_checker(app):
    while True:
        now = datetime.now(TIMEZONE)
        c.execute("SELECT id, user_id, text, time, repeat FROM reminders")
        for rid, uid, text, t, repeat in c.fetchall():
            dt = datetime.fromisoformat(t).astimezone(TIMEZONE)
            if now >= dt:
                kb = [[
                    InlineKeyboardButton("Через 1 час", callback_data=f"snooze_1h_{rid}"),
                    InlineKeyboardButton("Через 3 часа", callback_data=f"snooze_3h_{rid}"),
                    InlineKeyboardButton("До вечера", callback_data=f"snooze_eve_{rid}")
                ]]
                await app.bot.send_message(uid, f"🔔 Напоминание: {text}",
                                           reply_markup=InlineKeyboardMarkup(kb))
                if repeat == "once":
                    c.execute("DELETE FROM reminders WHERE id = ?", (rid,))
                elif repeat == "weekly":
                    new_time = dt + timedelta(days=7)
                    c.execute("UPDATE reminders SET time = ? WHERE id = ?", (new_time.isoformat(), rid))
                elif repeat == "monthly":
                    new_time = dt + timedelta(days=30)
                    c.execute("UPDATE reminders SET time = ? WHERE id = ?", (new_time.isoformat(), rid))
                conn.commit()
        await asyncio.sleep(60)

# =============== SNOOZE ===============
async def snooze_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    mins = {"1h": 60, "3h": 180, "eve": (datetime.now(TIMEZONE).replace(hour=20, minute=0) - datetime.now(TIMEZONE)).seconds // 60}
    offset = mins[parts[1]]
    rid = int(parts[2])
    c.execute("SELECT time FROM reminders WHERE id = ?", (rid,))
    t = datetime.fromisoformat(c.fetchone()[0]) + timedelta(minutes=offset)
    c.execute("UPDATE reminders SET time = ? WHERE id = ?", (t.isoformat(), rid))
    conn.commit()
    await query.edit_message_text("⏱ Напоминание отложено.")

# =============== MAIN ===============
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("list", list_reminders))
app.add_handler(CommandHandler("delete", delete_reminder))
app.add_handler(CallbackQueryHandler(snooze_callback, pattern=r"^snooze_"))

conv = ConversationHandler(
    entry_points=[CommandHandler("new", new_reminder)],
    states={
        TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_text)],
        TYPE: [CallbackQueryHandler(get_type)],
        TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
    },
    fallbacks=[]
)
app.add_handler(conv)

# Background reminder checker
app.job_queue.run_once(lambda c: asyncio.create_task(reminder_checker(app)), when=1)

# Run bot
app.run_polling()
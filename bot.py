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
c.execute("""CREATE TABLE IF NOT EXISTS reminders
             (user_id INTEGER, text TEXT, time TEXT, next_time TEXT, repeat TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT)""")
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
        c.execute("INSERT INTO reminders (user_id, text, time, next_time, repeat) VALUES (?, ?, ?, ?, ?)",
                  (update.effective_user.id, data["text"], dt.isoformat(), dt.isoformat(), data["repeat"]))
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

# =============== MAIN ===============
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("list", list_reminders))

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(asyncio.sleep(1))  # заглушка
    app.run_polling()

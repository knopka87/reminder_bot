# Reminder Telegram Bot with buttons, repeat options, and delay choices
# Works with python-telegram-bot v20+

import logging
from datetime import datetime, timedelta, time
import pytz
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CallbackContext, CommandHandler,
                          CallbackQueryHandler, MessageHandler, filters, ConversationHandler)
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

import sqlite3
import asyncio

# =============== CONFIGURATION ===============
TOKEN = os.environ.get("TOKEN")
TIMEZONE = pytz.timezone("Europe/Moscow")

# =============== DATABASE ===============
conn = sqlite3.connect("reminders.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS reminders
             (user_id INTEGER, text TEXT, time TEXT, next_time TEXT, repeat TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT)''')
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

async def delete_menu(update: Update, context: CallbackContext):
    c.execute("SELECT id, text FROM reminders WHERE user_id = ?", (update.effective_user.id,))
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text("У вас нет активных напоминаний.")
        return
    keyboard = [[InlineKeyboardButton(f"❌ {r[1]}", callback_data=f"del_{r[0]}")] for r in rows]
    await update.message.reply_text("Выберите напоминание для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_by_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    rid = int(query.data.split("_")[1])
    c.execute("DELETE FROM reminders WHERE user_id = ? AND id = ?", (query.from_user.id, rid))
    conn.commit()
    await query.edit_message_text("🗑 Напоминание удалено.")

# =============== REMINDER CHECK LOOP ===============
async def reminder_checker(app):
    while True:
        try:
            now = datetime.now(TIMEZONE)
            c.execute("SELECT id, user_id, text, time, next_time, repeat FROM reminders")
            for rid, uid, text, t, next_t, repeat in c.fetchall():
                try:
                    dt = datetime.fromisoformat(t).astimezone(TIMEZONE)
                    next_dt = datetime.fromisoformat(next_t).astimezone(TIMEZONE)
                    if now >= next_dt:
                        kb = [[
                            InlineKeyboardButton("⏱ Через 1 час", callback_data=f"snooze_1h_{rid}"),
                            InlineKeyboardButton("⏱ Через 3 часа", callback_data=f"snooze_3h_{rid}"),
                            InlineKeyboardButton("⏱ До вечера", callback_data=f"snooze_eve_{rid}"),
                            InlineKeyboardButton("⏱ Отложить на сутки", callback_data=f"snooze_tom_{rid}")
                        ],
                        [
                            InlineKeyboardButton("✅ Прочитано", callback_data=f"ack_{rid}")
                        ]]
                        msg = await app.bot.send_message(uid, f"🔔 Напоминание: {text}", 
                                                       reply_markup=InlineKeyboardMarkup(kb))
                        logging.info(f"Напоминание отправлено пользователю {uid}: {text} (ID: {rid})")
                except Exception as e:
                    logging.error(f"Ошибка при обработке напоминания {rid}: {str(e)}")
            await asyncio.sleep(20)
        except Exception as e:
            logging.error(f"Ошибка в цикле проверки напоминаний: {str(e)}")
            await asyncio.sleep(60)  # Увеличенная пауза при ошибке

# =============== ACKNOWLEDGE (READ) ===============
async def acknowledge_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    rid = int(query.data.split("_")[1])

    c.execute("SELECT repeat, time FROM reminders WHERE id = ?", (rid,))
    row = c.fetchone()
    if not row:
        await query.edit_message_text("🔕 Напоминание уже удалено.")
        return

    repeat, last_time = row
    if repeat == "once":
        c.execute("DELETE FROM reminders WHERE id = ?", (rid,))
        await query.edit_message_text("🗑 Напоминание удалено.")
    else:
        dt = datetime.fromisoformat(last_time).astimezone(TIMEZONE)
        if repeat == "weekly":
            new_time = dt + timedelta(days=7)
        elif repeat == "monthly":
            new_time = dt + timedelta(days=30)
        else:
            new_time = dt
        c.execute("UPDATE reminders SET time = ?, next_time = ? WHERE id = ?", (new_time.isoformat(), new_time.isoformat(), rid))
        await query.edit_message_text("🔁 Напоминание перенесено на следующий период.")
    conn.commit()

# =============== SNOOZE ===============
async def snooze_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    mins = {"1h": 60, "3h": 180, "eve": (datetime.now(TIMEZONE).replace(hour=20, minute=0) - datetime.now(TIMEZONE)).seconds // 60, "tom": (datetime.now(TIMEZONE).replace(hour=9, minute=0) + timedelta(days=1) - datetime.now(TIMEZONE)).seconds // 60}
    offset = mins[parts[1]]
    rid = int(parts[2])
    new_time = datetime.now(TIMEZONE) + timedelta(minutes=offset)
    c.execute("UPDATE reminders SET next_time = ? WHERE id = ?", (new_time.isoformat(), rid))
    conn.commit()
    await query.edit_message_text("⏱ Напоминание отложено.")

# =============== HEALTH CHECK ===============
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Not Found")
            
    def log_message(self, format, *args):
        return  # Отключаем логирование HTTP запросов

def start_health_check():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server

# =============== MAIN ===============
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("list", list_reminders))
app.add_handler(CommandHandler("delete", delete_menu))
app.add_handler(CallbackQueryHandler(delete_by_button, pattern=r"^del_"))
app.add_handler(CallbackQueryHandler(snooze_callback, pattern=r"^snooze_"))
app.add_handler(CallbackQueryHandler(acknowledge_callback, pattern=r"^ack_"))

conv = ConversationHandler(
    entry_points=[CommandHandler("new", new_reminder)],
    states={
        TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_text)],
        TYPE: [CallbackQueryHandler(get_type, pattern=r"^(once|weekly|monthly)$", block=False)],
        TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
    },
    fallbacks=[]
)
app.add_handler(conv)

# Background reminder checker
if __name__ == "__main__":
    async def run():
        # Запускаем health check сервер
        health_server = start_health_check()
        logging.info("Health check сервер запущен на порту 8080")
        
        async with app:
            reminder_task = asyncio.create_task(reminder_checker(app))
            await app.start()
            await app.updater.start_polling()

            try:
                stop = asyncio.Future()
                await stop
            except (KeyboardInterrupt, SystemExit):
                logging.info("Получен сигнал завершения...")
            finally:
                reminder_task.cancel()
                try:
                    await reminder_task
                except asyncio.CancelledError:
                    pass
                await app.stop()
                health_server.shutdown()  # Останавливаем health check сервер
                health_server.server_close()
                logging.info("Бот остановлен")

    asyncio.run(run())

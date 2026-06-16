import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message, ErrorEvent
import aiosqlite

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "TELEGRAM_BOT_TOKEN"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

async def init_db():
    async with aiosqlite.connect("chat_ratings.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                user_id INTEGER,
                chat_id INTEGER,
                username TEXT,
                first_name TEXT,
                points INTEGER DEFAULT 0,
                last_message_date TEXT,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        await db.commit()

# ✅ ИСПРАВЛЕНО: Явно исключаем команды в фильтре
@router.message(
    lambda msg: msg.chat.type in ['group', 'supergroup'] and
                not (msg.text and msg.text.startswith('/'))
)
async def count_message(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return

    user = message.from_user
    chat_id = message.chat.id

    try:
        async with aiosqlite.connect("chat_ratings.db") as db:
            cursor = await db.execute(
                "SELECT points FROM user_points WHERE user_id = ? AND chat_id = ?",
                (user.id, chat_id)
            )
            result = await cursor.fetchone()

            if result:
                await db.execute(
                    """UPDATE user_points
                       SET points = points + 1, username = ?, first_name = ?,
                           last_message_date = ?
                       WHERE user_id = ? AND chat_id = ?""",
                    (user.username, user.first_name,
                     datetime.now().isoformat(), user.id, chat_id)
                )
            else:
                await db.execute(
                    """INSERT INTO user_points
                       (user_id, chat_id, username, first_name, points, last_message_date)
                       VALUES (?, ?, ?, ?, 1, ?)""",
                    (user.id, chat_id, user.username, user.first_name,
                     datetime.now().isoformat())
                )
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка при начислении очков: {e}")

@router.message(Command("start", ignore_case=True))
async def start_command(message: Message):
    await message.reply(
        "👋 Привет! Я бот для рейтинга в чатах.\n\n"
        "📝 Пишите сообщения в чатах, где я есть, чтобы зарабатывать очки.\n"
        "📊 Используйте команду /top, чтобы увидеть общий рейтинг участников.\n\n"
        "Добавьте меня в группу и сделайте администратором!"
    )

@router.message(Command("help", ignore_case=True))
async def help_command(message: Message):
    await message.reply(
        "🤖 Как пользоваться ботом:\n\n"
        "1. Добавьте бота в групповой чат\n"
        "2. Участники получают по 1 очку за каждое сообщение\n"
        "3. Используйте /top для просмотра общего рейтинга\n"
        "4. Очки суммируются со всех чатов\n\n"
        "📌 Команды:\n"
        "/start - информация\n/help - помощь\n/top - рейтинг"
    )

@router.message(Command("top", ignore_case=True))
async def top_command(message: Message):
    try:
        async with aiosqlite.connect("chat_ratings.db") as db:
            cursor = await db.execute("""
                SELECT user_id, MAX(username), MAX(first_name),
                       SUM(points), COUNT(DISTINCT chat_id)
                FROM user_points
                GROUP BY user_id
                ORDER BY SUM(points) DESC
                LIMIT 10
            """)
            top_users = await cursor.fetchall()

            if not top_users:
                await message.answer("📊 Рейтинг пока пуст.")
                return

            text = "🏆 Топ-10 участников:\n\n"
            medals = ["🥇", "🥈", "🥉"] + ["👑"] * 7

            for i, (uid, uname, fname, pts, chats) in enumerate(top_users, 1):
                name = f"@{uname}" if uname else (fname or f"User{uid}")
                text += f"{medals[i-1]} {i}. {name}\n"
                text += f"   📊 {pts} очков | 💬 {chats} чат(ов)\n\n"

            uid = message.from_user.id
            cursor = await db.execute(
                "SELECT COALESCE(SUM(points),0), COUNT(DISTINCT chat_id) FROM user_points WHERE user_id = ?",
                (uid,)
            )
            stats = await cursor.fetchone()

            if stats and stats[0] > 0 and not any(u[0] == uid for u in top_users):
                cursor = await db.execute("""
                    SELECT COUNT(*)+1 FROM (
                        SELECT user_id, SUM(points) tp FROM user_points
                        GROUP BY user_id HAVING tp > ?
                    )
                """, (stats[0],))
                pos = (await cursor.fetchone())[0]
                text += f"━━━━━━━━━━\n📌 Ваша позиция: {pos}\n📊 {stats[0]} очков | 💬 {stats[1]} чат(ов)"

            await message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка top: {e}")
        await message.answer("❌ Ошибка при получении рейтинга")

@router.message(lambda msg: msg.chat.type == 'private')
async def private_handler(message: Message):
    if not message.text or not message.text.startswith('/'):
        await message.reply(
            "Используйте команды:\n"
            "/start - информация\n"
            "/help - помощь\n"
            "/top - рейтинг"
        )

@dp.errors()
async def error_handler(event: ErrorEvent):
    logger.error(f"Ошибка: {event.exception}")
    return True

async def main():
    await init_db()
    dp.include_router(router)
    logger.info("Бот запущен!")
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

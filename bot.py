"""
Telegram-бот + сервер для мини-игры «Соедини точки» с рейтингом.

Запуск:
    pip install -r requirements.txt
    export BOT_TOKEN="123:ABC..."
    export WEBAPP_URL="https://ваш-домен.example"   # обязательно HTTPS
    python bot.py
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, WebAppInfo)

BOT_TOKEN = os.environ["BOT_TOKEN"]
# На Render адрес сервиса подставляется автоматически (RENDER_EXTERNAL_URL)
WEBAPP_URL = (os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/vibexxxapk")
PORT = int(os.getenv("PORT", "8080"))
DB_PATH = os.getenv("DB_PATH", "game.db")
BASE_DIR = Path(__file__).parent

MAX_SCORE_PER_LEVEL = 700      # потолок очков за уровень (защита от накрутки)
INITDATA_TTL = 24 * 3600       # initData действует сутки

logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------- БАЗА
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id    INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                best_score INTEGER NOT NULL DEFAULT 0,
                best_level INTEGER NOT NULL DEFAULT 1,
                updated_at INTEGER NOT NULL
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_score ON players(best_score DESC)")


def save_score(user_id: int, name: str, score: int, level: int):
    now = int(time.time())
    with db() as c:
        c.execute("""
            INSERT INTO players (user_id, name, best_score, best_level, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                best_level = CASE WHEN excluded.best_score > best_score
                                  THEN excluded.best_level ELSE best_level END,
                best_score = MAX(best_score, excluded.best_score),
                updated_at = excluded.updated_at
        """, (user_id, name, score, level, now))


def top_players(limit=20):
    with db() as c:
        return c.execute(
            "SELECT user_id, name, best_score FROM players "
            "WHERE best_score > 0 ORDER BY best_score DESC, updated_at ASC LIMIT ?",
            (limit,)).fetchall()


def my_position(user_id: int):
    with db() as c:
        row = c.execute("SELECT best_score FROM players WHERE user_id = ?", (user_id,)).fetchone()
        if not row or row["best_score"] <= 0:
            return None, 0
        rank = c.execute("SELECT COUNT(*) FROM players WHERE best_score > ?",
                         (row["best_score"],)).fetchone()[0] + 1
        return rank, row["best_score"]


# ---------------------------------------------------------------- ПРОВЕРКА initData
def verify_init_data(init_data: str):
    """Проверяет подпись Telegram. Возвращает dict пользователя или None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        if time.time() - int(pairs.get("auth_date", 0)) > INITDATA_TTL:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


def display_name(user: dict) -> str:
    return (user.get("username") or user.get("first_name") or f"id{user['id']}")[:32]


# ---------------------------------------------------------------- HTTP API
async def index(_request):
    return web.FileResponse(BASE_DIR / "index.html")


async def health(_request):
    return web.Response(text="ok")


async def api_score(request):
    data = await request.json()
    user = verify_init_data(data.get("initData", ""))
    if not user:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    try:
        score, level = int(data["score"]), int(data["level"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"ok": False, "error": "bad_data"}, status=400)
    if not (0 <= score <= level * MAX_SCORE_PER_LEVEL and 1 <= level <= 1000):
        return web.json_response({"ok": False, "error": "implausible"}, status=400)
    save_score(user["id"], display_name(user), score, level)
    return web.json_response({"ok": True})


async def api_leaderboard(request):
    data = await request.json()
    user = verify_init_data(data.get("initData", ""))
    if not user:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    top = [{"name": r["name"], "score": r["best_score"], "me": r["user_id"] == user["id"]}
           for r in top_players(20)]
    rank, score = my_position(user["id"])
    return web.json_response({"ok": True, "top": top, "my_rank": rank, "my_score": score})


# ---------------------------------------------------------------- БОТ
dp = Dispatcher()


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="📢 Наш канал", url=CHANNEL_URL)],
    ])


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🎯 Соединяй точки по порядку, набирай очки и поднимайся в рейтинге!\n"
        f"📢 Наш канал: {CHANNEL_URL}",
        reply_markup=main_kb(), disable_web_page_preview=True)


@dp.message(Command("top"))
async def cmd_top(message: Message):
    rows = top_players(10)
    if not rows:
        await message.answer("Пока никого в рейтинге. Будь первым! 🎮", reply_markup=main_kb())
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else str(i + 1) + '.'} {r['name']} — {r['best_score']}"
             for i, r in enumerate(rows)]
    rank, score = my_position(message.from_user.id)
    footer = f"\n\nВаше место: #{rank} ({score})" if rank else ""
    await message.answer("🏆 Топ игроков\n\n" + "\n".join(lines) + footer, reply_markup=main_kb())


# ---------------------------------------------------------------- ЗАПУСК
async def main():
    if not WEBAPP_URL:
        logging.warning("WEBAPP_URL не задан: кнопка «Играть» работать не будет")
    init_db()
    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.get("/health", health),
        web.post("/api/score", api_score),
        web.post("/api/leaderboard", api_leaderboard),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logging.info("Web server on :%s", PORT)

    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

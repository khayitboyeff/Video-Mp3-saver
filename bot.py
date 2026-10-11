import os
import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.exceptions import TelegramBadRequest
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("saverbot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "50000"))  # Keep below Telegram bot upload limits.
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@CyberSecurity_full_course").strip()
CHANNEL_URL = "https://t.me/" + REQUIRED_CHANNEL.lstrip("@")
DB_PATH = Path(os.getenv("SAVERBOT_DB", "saverbot.sqlite3"))
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
active_tasks = {}  # user_id -> asyncio.Task
cancel_flags = set()
pending = {}

LANGS = {
    "uz": {
        "welcome": "👋 SaverBot’ga xush kelibsiz!\nIstalgan saytning video havolasini yuboring. Video yoki MP3 formatini tanlashingiz mumkin.",
        "menu": "Bosh menyu",
        "settings": "🌐 Tilni tanlash",
        "admin": "🛠 Admin panel",
        "cancel": "❌ Bekor qilish",
        "working": "⏳ Yuklash boshlandi…",
        "sending": "📤 Telegramga yuborilmoqda…",
        "bad_url": "❌ To‘g‘ri http:// yoki https:// havola yuboring. Sayt yt-dlp tomonidan qo‘llab-quvvatlanishi kerak.",
        "failed": "❌ Yuklab bo‘lmadi. Havolani yoki video cheklovlarini tekshiring.",
        "limit": "",
        "choose": "Nimani yuklamoqchisiz?",
        "video": "🎬 Video",
        "audio": "🎵 MP3 audio",
        "quality": "🎚 Sifatni tanlang",
        "quality_note": "Tanlangan sifat taxminiy: manbada mavjud formatlar bilan cheklangan.",
        "cancelled": "Yuklash bekor qilindi.",
        "not_admin": "Bu buyruq faqat admin uchun.",
        "choose_lang": "Tilni tanlang:",
        "sub_required": "🔒 Botdan foydalanish uchun avval @CyberSecurity_full_course kanaliga obuna bo‘ling, keyin /checksub buyrug‘ini yuboring.",
        "check_sub": "🔎 Obunani tekshirish",
        "sub_ok": "✅ Obuna tasdiqlandi. Botdan foydalanishingiz mumkin.",
    },
    "ru": {
        "welcome": "👋 Добро пожаловать в SaverBot!\nОтправьте ссылку на видео с поддерживаемого сайта. Можно выбрать видео или MP3.",
        "menu": "Главное меню",
        "settings": "🌐 Выбрать язык",
        "admin": "🛠 Панель администратора",
        "cancel": "❌ Отмена",
        "working": "⏳ Загрузка началась…",
        "sending": "📤 Отправка в Telegram…",
        "bad_url": "❌ Отправьте корректную ссылку http:// или https://. Сайт должен поддерживаться yt-dlp.",
        "failed": "❌ Не удалось скачать. Проверьте ссылку или ограничения видео.",
        "limit": "⛔ Дневной бесплатный лимит исчерпан. Откройте /pro.",
        "choose": "Что скачать?",
        "video": "🎬 Видео",
        "audio": "🎵 MP3 аудио",
        "quality": "🎚 Выбрать качество",
        "quality_note": "Качество зависит от доступных форматов источника.",
        "cancelled": "Загрузка отменена.",
        "not_admin": "Эта команда доступна только администратору.",
        "choose_lang": "Выберите язык:",
        "sub_required": "🔒 Сначала подпишитесь на канал @CyberSecurity_full_course, затем отправьте /checksub.",
        "check_sub": "🔎 Проверить подписку",
        "sub_ok": "✅ Подписка подтверждена. Можно пользоваться ботом.",
    },
    "en": {
        "welcome": "👋 Welcome to SaverBot!\nSend a video link from a supported website. Choose video or MP3.",
        "menu": "Main menu",
        "settings": "🌐 Choose language",
        "admin": "🛠 Admin panel",
        "cancel": "❌ Cancel",
        "working": "⏳ Download started…",
        "sending": "📤 Sending to Telegram…",
        "bad_url": "❌ Send a valid http:// or https:// link. The website must be supported by yt-dlp.",
        "failed": "❌ Download failed. Check the link or video restrictions.",
        "limit": "⛔ Daily free limit reached. Open /pro.",
        "choose": "What would you like to download?",
        "video": "🎬 Video",
        "audio": "🎵 MP3 audio",
        "quality": "🎚 Choose quality",
        "quality_note": "Quality depends on formats available from the source.",
        "cancelled": "Download cancelled.",
        "not_admin": "This command is admin-only.",
        "choose_lang": "Choose a language:",
    },
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'uz',
            pro_until INTEGER DEFAULT 0, created_at INTEGER NOT NULL,
            language_selected INTEGER NOT NULL DEFAULT 0)""")
        columns = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}
        if "language_selected" not in columns:
            c.execute("ALTER TABLE users ADD COLUMN language_selected INTEGER NOT NULL DEFAULT 0")
        c.execute("""CREATE TABLE IF NOT EXISTS downloads(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            url TEXT NOT NULL, platform TEXT NOT NULL, kind TEXT NOT NULL,
            result TEXT NOT NULL, created_at INTEGER NOT NULL)""")

def get_user(uid):
    with db() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def ensure_user(user: types.User):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id, username, created_at) VALUES(?,?,?)",
                  (user.id, user.username or "", int(time.time())))
        c.execute("UPDATE users SET username=? WHERE user_id=?", (user.username or "", user.id))

def lang_of(uid):
    row = get_user(uid)
    return (row["lang"] if row and row["lang"] in LANGS else "uz")

def tr(uid, key):
    return LANGS[lang_of(uid)].get(key, LANGS["uz"].get(key, key))

def platform_for(url):
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None

async def is_subscribed(uid: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, uid)
        return member.status not in {"left", "kicked"}
    except Exception as exc:
        log.warning("Could not verify membership in %s: %s", REQUIRED_CHANNEL, exc)
        return False

def subscription_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=CHANNEL_URL)],
        [InlineKeyboardButton(text=tr(uid, "check_sub"), callback_data="checksub")],
    ])

async def require_subscription(message_or_call, uid: int) -> bool:
    if await is_subscribed(uid):
        return True
    text = tr(uid, "sub_required")
    if isinstance(message_or_call, types.Message):
        await message_or_call.answer(text, reply_markup=subscription_keyboard(uid))
    else:
        await message_or_call.message.answer(text, reply_markup=subscription_keyboard(uid))
        await message_or_call.answer()
    return False

def main_keyboard(uid):
    row = get_user(uid)
    rows = []
    if not row or not row["language_selected"]:
        rows.append([InlineKeyboardButton(text=tr(uid, "settings"), callback_data="language")])
    if uid in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text=tr(uid, "admin"), callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def choices_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(uid, "video"), callback_data="kind:video"),
         InlineKeyboardButton(text=tr(uid, "audio"), callback_data="kind:audio")],
        [InlineKeyboardButton(text=tr(uid, "quality"), callback_data="quality")],
        [InlineKeyboardButton(text=tr(uid, "cancel"), callback_data="cancel")],
    ])

@dp.message(CommandStart())
async def start(message: types.Message):
    ensure_user(message.from_user)
    uid = message.from_user.id
    if not await is_subscribed(uid):
        await message.answer(tr(uid, "sub_required"), reply_markup=subscription_keyboard(uid))
        return
    await message.answer(tr(uid, "welcome"), reply_markup=main_keyboard(uid))

@dp.message(Command("checksub"))
async def check_sub_command(message: types.Message):
    ensure_user(message.from_user)
    uid = message.from_user.id
    if await is_subscribed(uid):
        await message.answer(tr(uid, "sub_ok"), reply_markup=main_keyboard(uid))
    else:
        await message.answer(tr(uid, "sub_required"), reply_markup=subscription_keyboard(uid))

@dp.callback_query(F.data == "checksub")
async def check_sub_callback(call: types.CallbackQuery):
    ensure_user(call.from_user)
    uid = call.from_user.id
    if await is_subscribed(uid):
        await call.message.answer(tr(uid, "sub_ok"), reply_markup=main_keyboard(uid))
        await call.answer("✅")
    else:
        await call.answer("Hali kanalga obuna bo‘lmagansiz.", show_alert=True)

@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "📖 Buyruqlar:\n/start — boshlash\n/history — yuklashlar tarixi\n"
        "/pro — PRO holati\n/checksub — kanal obunasini tekshirish\n"
        "/video URL — video yuklash\n/mp3 URL — MP3 yuklash\n/quality 720 URL — sifat bilan video\n"
        "/language — tilni tanlash\n/id — Telegram ID\n"
        "Admin: /stats"
    )

@dp.message(Command("language"))
async def language_command(message: types.Message):
    ensure_user(message.from_user)
    if not await require_subscription(message, message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O‘zbekcha", callback_data="lang:uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ])
    await message.answer(tr(message.from_user.id, "choose_lang"), reply_markup=kb)

@dp.message(Command("id"))
async def id_command(message: types.Message):
    await message.answer(f"Your Telegram ID: {message.from_user.id}")

@dp.message(Command("stats"))
async def stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(tr(message.from_user.id, "not_admin"))
        return
    with db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await message.answer(f"📊 SaverBot statistikasi\nFoydalanuvchilar: {users}")

async def command_download(message: types.Message, kind: str):
    ensure_user(message.from_user)
    uid = message.from_user.id
    if not await require_subscription(message, uid):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            f"Foydalanish: /{'video' if kind == 'video' else 'mp3'} https://...\n"
            "Sifat uchun: /quality 720 https://..."
        )
        return
    url = parts[1].strip()
    platform = platform_for(url)
    if not platform:
        await message.answer(tr(uid, "bad_url"))
        return
    if uid in active_tasks:
        await message.answer("Sizda yuklash jarayoni allaqachon bor.")
        return
    item = {"url": url, "platform": platform, "quality": "best"}
    active_tasks[uid] = asyncio.create_task(do_download(message, uid, item, kind))

@dp.message(Command("video"))
async def video_command(message: types.Message):
    await command_download(message, "video")

@dp.message(Command("mp3"))
async def mp3_command(message: types.Message):
    await command_download(message, "audio")

@dp.message(Command("quality"))
async def quality_command(message: types.Message):
    ensure_user(message.from_user)
    uid = message.from_user.id
    if not await require_subscription(message, uid):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or parts[1] not in {"360", "480", "720", "1080", "best"}:
        await message.answer("Foydalanish: /quality 720 https://youtube.com/...\nVariantlar: 360, 480, 720, 1080, best")
        return
    quality, url = parts[1], parts[2].strip()
    platform = platform_for(url)
    if not platform:
        await message.answer(tr(uid, "bad_url"))
        return
    if uid in active_tasks:
        await message.answer("Sizda yuklash jarayoni allaqachon bor.")
        return
    item = {"url": url, "platform": platform, "quality": quality}
    active_tasks[uid] = asyncio.create_task(do_download(message, uid, item, "video"))

@dp.message(F.text.startswith("http"))
async def receive_url(message: types.Message):
    ensure_user(message.from_user)
    if not await require_subscription(message, message.from_user.id):
        return
    url = (message.text or "").strip()
    platform = platform_for(url)
    if not platform:
        await message.answer(tr(message.from_user.id, "bad_url"))
        return
    pending[message.from_user.id] = {"url": url, "platform": platform, "quality": "best"}
    await message.answer(tr(message.from_user.id, "choose"), reply_markup=choices_keyboard(message.from_user.id))

@dp.callback_query(F.data == "language")
async def language_menu(call: types.CallbackQuery):
    if not await is_subscribed(call.from_user.id):
        await call.message.answer(tr(call.from_user.id, "sub_required"), reply_markup=subscription_keyboard(call.from_user.id))
        await call.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O‘zbekcha", callback_data="lang:uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ])
    await call.message.answer(tr(call.from_user.id, "choose_lang"), reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("lang:"))
async def set_language(call: types.CallbackQuery):
    if not await is_subscribed(call.from_user.id):
        await call.message.answer(tr(call.from_user.id, "sub_required"), reply_markup=subscription_keyboard(call.from_user.id))
        await call.answer()
        return
    code = call.data.split(":", 1)[1]
    if code not in LANGS:
        await call.answer()
        return
    with db() as c:
        c.execute("UPDATE users SET lang=?, language_selected=1 WHERE user_id=?", (code, call.from_user.id))
    await call.message.answer(tr(call.from_user.id, "welcome"), reply_markup=main_keyboard(call.from_user.id))
    await call.answer("OK")

@dp.callback_query(F.data == "admin")
async def admin_menu(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("No access", show_alert=True)
        return
    with db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await call.message.answer(
        f"🛠 Admin panel\n👥 Users: {users}\n\nCommands:\n/stats\n/id",
        reply_markup=main_keyboard(call.from_user.id)
    )
    await call.answer()

@dp.callback_query(F.data == "quality")
async def quality_menu(call: types.CallbackQuery):
    uid = call.from_user.id
    if not await is_subscribed(uid):
        await call.message.answer(tr(uid, "sub_required"), reply_markup=subscription_keyboard(uid))
        await call.answer()
        return
    if uid not in pending:
        await call.answer("Avval havola yuboring.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="360p", callback_data="q:360"),
         InlineKeyboardButton(text="480p", callback_data="q:480")],
        [InlineKeyboardButton(text="720p", callback_data="q:720"),
         InlineKeyboardButton(text="1080p", callback_data="q:1080")],
        [InlineKeyboardButton(text="Eng yaxshi", callback_data="q:best")],
    ])
    await call.message.answer(tr(uid, "quality_note"), reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("q:"))
async def set_quality(call: types.CallbackQuery):
    uid = call.from_user.id
    if not await is_subscribed(uid):
        await call.message.answer(tr(uid, "sub_required"), reply_markup=subscription_keyboard(uid))
        await call.answer()
        return
    if uid in pending:
        pending[uid]["quality"] = call.data.split(":", 1)[1]
        await call.message.answer("✅ Sifat tanlandi. Endi Video yoki MP3 tugmasini bosing.", reply_markup=choices_keyboard(uid))
        await call.answer()

@dp.callback_query(F.data.startswith("kind:"))
async def choose_kind(call: types.CallbackQuery):
    uid = call.from_user.id
    if not await is_subscribed(uid):
        await call.message.answer(tr(uid, "sub_required"), reply_markup=subscription_keyboard(uid))
        await call.answer()
        return
    item = pending.get(uid)
    if not item:
        await call.answer("Avval havola yuboring.", show_alert=True)
        return
    kind = call.data.split(":", 1)[1]
    if kind not in {"video", "audio"}:
        await call.answer()
        return
    if uid in active_tasks:
        await call.answer("Sizda yuklash jarayoni allaqachon bor.", show_alert=True)
        return
    task = asyncio.create_task(do_download(call.message, uid, item.copy(), kind))
    active_tasks[uid] = task
    await call.answer()

async def do_download(message, uid, item, kind):
    url, platform, quality = item["url"], item["platform"], item["quality"]
    status = await message.answer(tr(uid, "working"), reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "cancel"), callback_data="cancel")]]
    ))
    output_path = None
    last_edit = 0
    loop = asyncio.get_running_loop()

    def hook(data):
        nonlocal last_edit
        if uid in cancel_flags:
            raise Exception("Download cancelled by user")
        now = time.time()
        if data.get("status") == "downloading" and now - last_edit > 2:
            last_edit = now
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            got = data.get("downloaded_bytes") or 0
            percent = int(got * 100 / total) if total else 0
            text = f"⏳ {platform}: {percent}%"
            asyncio.run_coroutine_threadsafe(safe_edit(status, text), loop)

    def run_ytdlp():
        if kind == "audio":
            fmt = "bestaudio/best"
        else:
            if quality == "best":
                fmt = "bestvideo+bestaudio/best"
            else:
                fmt = (
                    f"bestvideo[height<={quality}]+bestaudio/"
                    f"best[height<={quality}]/bestvideo+bestaudio/best"
                )

        opts = {
            "outtmpl": str(DOWNLOAD_DIR / f"{uid}_%(id)s.%(ext)s"),
            "format": fmt,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "max_filesize": MAX_DOWNLOAD_MB * 1024 * 1024,
            "progress_hooks": [hook],
        }

        if kind == "audio":
            opts.update({
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })

        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            name = ydl.prepare_filename(info)
            p = Path(name)

            if kind == "audio":
                p = p.with_suffix(".mp3")

            return p

    try:
        output_path = await asyncio.to_thread(run_ytdlp)
        if uid in cancel_flags:
            raise asyncio.CancelledError()
        
        if not output_path or not output_path.exists():
            candidates = sorted(DOWNLOAD_DIR.glob(f"{uid}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                output_path = candidates[0]
                
        if not output_path or not output_path.exists():
            raise FileNotFoundError("Downloaded output not found")

        size_mb = output_path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_DOWNLOAD_MB:
            raise ValueError(f"File too large: {size_mb:.1f} MB")

        await safe_edit(status, tr(uid, "sending"))

        if kind == "audio":
            await message.answer_audio(FSInputFile(output_path), caption=f"🎵 {platform} audio")
        else:
            try:
                await message.answer_video(FSInputFile(output_path), caption=f"✅ {platform} video")
            except Exception:
                await message.answer_document(FSInputFile(output_path), caption=f"📁 {platform} video")

        await safe_edit(status, "✅ Tayyor!")
    except asyncio.CancelledError:
        await safe_edit(status, tr(uid, "cancelled"))
    except Exception:
        log.exception("Download failed for user %s", uid)
        await safe_edit(status, tr(uid, "failed"))
    finally:
        cancel_flags.discard(uid)
        active_tasks.pop(uid, None)
        if output_path and output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        for p in DOWNLOAD_DIR.glob(f"{uid}_*"):
            try:
                p.unlink()
            except OSError:
                pass

async def safe_edit(message, text):
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        pass
    except Exception:
        log.exception("Could not edit status message")

@dp.callback_query(F.data == "cancel")
async def cancel_download(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid in active_tasks:
        cancel_flags.add(uid)
        await call.answer("Bekor qilish so‘rovi yuborildi.")
    else:
        pending.pop(uid, None)
        await call.answer("Faol yuklash yo‘q.")

@dp.message(F.text)
async def other_text(message: types.Message):
    ensure_user(message.from_user)
    await message.answer(tr(message.from_user.id, "welcome"), reply_markup=main_keyboard(message.from_user.id))

async def main():
    init_db()
    log.info("SaverBot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
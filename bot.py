import asyncio
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("saverbot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
MAX_DOWNLOAD_MB = max(1, int(os.getenv("MAX_DOWNLOAD_MB", "45")))
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@CyberSecurity_full_course").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")
DB_PATH = Path(os.getenv("SAVERBOT_DB", "saverbot.sqlite3"))
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing. Railway Variables bo'limiga BOT_TOKEN kiriting.")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
active_tasks: dict[int, asyncio.Task] = {}
cancel_flags: set[int] = set()
pending: dict[int, dict] = {}

LANGS = {
    "uz": {
        "welcome": "👋 SaverBot’ga xush kelibsiz!\nYouTube, Instagram yoki qo‘llab-quvvatlanadigan sayt havolasini yuboring.",
        "settings": "🌐 Tilni tanlash", "admin": "🛠 Admin panel", "cancel": "❌ Bekor qilish",
        "working": "⏳ Yuklash boshlandi…", "sending": "📤 Telegramga yuborilmoqda…",
        "bad_url": "❌ To‘g‘ri http/https havola yuboring.",
        "failed": "❌ Yuklab bo‘lmadi. Havolani tekshiring yoki boshqa havolani sinab ko‘ring.",
        "choose": "Nimani yuklamoqchisiz?", "video": "🎬 Video", "audio": "🎵 MP3 audio",
        "quality": "🎚 Sifatni tanlash", "quality_note": "Video sifatini tanlang:",
        "cancelled": "Yuklash bekor qilindi.", "not_admin": "Bu buyruq faqat admin uchun.",
        "choose_lang": "Tilni tanlang:", "sub_required": f"🔒 Davom etish uchun {REQUIRED_CHANNEL} kanaliga obuna bo‘ling.",
        "check_sub": "🔎 Obunani tekshirish", "sub_ok": "✅ Obuna tasdiqlandi.",
        "yt_blocked": "⚠️ YouTube ushbu videoni hozir yuklashga ruxsat bermayapti (bot tekshiruvi/login talabi). Birozdan keyin yoki boshqa havola bilan urinib ko‘ring.",
        "too_large": "⚠️ Fayl hajmi Telegram bot limitidan katta. Qisqaroq video yoki pastroq sifatni tanlang.",
    },
    "ru": {
        "welcome": "👋 Добро пожаловать в SaverBot! Отправьте ссылку на поддерживаемое видео.",
        "settings": "🌐 Язык", "admin": "🛠 Админ-панель", "cancel": "❌ Отмена",
        "working": "⏳ Загрузка началась…", "sending": "📤 Отправка в Telegram…",
        "bad_url": "❌ Отправьте корректную ссылку http/https.", "failed": "❌ Не удалось скачать. Проверьте ссылку.",
        "choose": "Что скачать?", "video": "🎬 Видео", "audio": "🎵 MP3 аудио",
        "quality": "🎚 Качество", "quality_note": "Выберите качество видео:",
        "cancelled": "Загрузка отменена.", "not_admin": "Команда только для администратора.",
        "choose_lang": "Выберите язык:", "sub_required": f"🔒 Сначала подпишитесь на {REQUIRED_CHANNEL}.",
        "check_sub": "🔎 Проверить подписку", "sub_ok": "✅ Подписка подтверждена.",
        "yt_blocked": "⚠️ YouTube требует вход или проверку. Попробуйте позже или другую ссылку.",
        "too_large": "⚠️ Файл слишком большой для отправки ботом.",
    },
    "en": {
        "welcome": "👋 Welcome to SaverBot! Send a link from a supported website.",
        "settings": "🌐 Language", "admin": "🛠 Admin panel", "cancel": "❌ Cancel",
        "working": "⏳ Download started…", "sending": "📤 Sending to Telegram…",
        "bad_url": "❌ Send a valid http/https link.", "failed": "❌ Download failed. Check the link.",
        "choose": "What would you like to download?", "video": "🎬 Video", "audio": "🎵 MP3 audio",
        "quality": "🎚 Quality", "quality_note": "Choose video quality:",
        "cancelled": "Download cancelled.", "not_admin": "Admin-only command.",
        "choose_lang": "Choose a language:", "sub_required": f"🔒 Subscribe to {REQUIRED_CHANNEL} first.",
        "check_sub": "🔎 Check subscription", "sub_ok": "✅ Subscription confirmed.",
        "yt_blocked": "⚠️ YouTube requires sign-in or an additional check. Try later or use another link.",
        "too_large": "⚠️ File is too large to send through this bot.",
    },
}

def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'uz',
            pro_until INTEGER DEFAULT 0, created_at INTEGER NOT NULL,
            language_selected INTEGER NOT NULL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS downloads(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            url TEXT NOT NULL, platform TEXT NOT NULL, kind TEXT NOT NULL,
            result TEXT NOT NULL, created_at INTEGER NOT NULL)""")

def ensure_user(user: types.User):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id,username,created_at) VALUES(?,?,?)",
                  (user.id, user.username or "", int(time.time())))
        c.execute("UPDATE users SET username=? WHERE user_id=?", (user.username or "", user.id))

def get_user(uid):
    with db() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def lang_of(uid):
    row = get_user(uid)
    return row["lang"] if row and row["lang"] in LANGS else "uz"

def tr(uid, key):
    return LANGS[lang_of(uid)].get(key, LANGS["uz"].get(key, key))

def platform_for(url):
    try:
        p = urlparse(url.strip())
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
        host = p.hostname.lower()
        if host == "localhost" or host.endswith(".local"):
            return None
        return host.removeprefix("www.")
    except Exception:
        return None

def is_pro(uid):
    row = get_user(uid)
    return bool(row and row["pro_until"] and row["pro_until"] > int(time.time()))

def add_history(uid, url, platform, kind, result):
    with db() as c:
        c.execute("INSERT INTO downloads(user_id,url,platform,kind,result,created_at) VALUES(?,?,?,?,?,?)",
                  (uid, url[:1500], platform, kind, result, int(time.time())))

async def is_subscribed(uid: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, uid)
        return member.status not in {"left", "kicked"}
    except Exception as exc:
        log.warning("Subscription check failed for %s: %s", REQUIRED_CHANNEL, exc)
        return False

def subscription_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=CHANNEL_URL)],
        [InlineKeyboardButton(text=tr(uid, "check_sub"), callback_data="checksub")],
    ])

async def require_subscription(message_or_call, uid):
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
    rows = [[InlineKeyboardButton(text=tr(uid, "settings"), callback_data="language")]]
    if uid in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text=tr(uid, "admin"), callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def choices_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(uid, "video"), callback_data="kind:video"),
         InlineKeyboardButton(text=tr(uid, "audio"), callback_data="kind:audio")],
        [InlineKeyboardButton(text=tr(uid, "quality"), callback_data="quality")],
        [InlineKeyboardButton(text=tr(uid, "cancel"), callback_data="cancel")]
    ])

@dp.message(CommandStart())
async def start(message: types.Message):
    ensure_user(message.from_user)
    uid = message.from_user.id
    if not await require_subscription(message, uid):
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
        await call.answer("Hali obuna aniqlanmadi.", show_alert=True)

@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "📖 Buyruqlar:\n/start — boshlash\n/history — tarix\n/pro — PRO holati\n"
        "/checksub — obunani tekshirish\n/video URL — video\n/mp3 URL — MP3\n"
        "/quality 720 URL — sifatli video\n/language — til\n/id — Telegram ID\n/stats — admin statistikasi"
    )

@dp.message(Command("id"))
async def id_command(message: types.Message):
    await message.answer(f"Telegram ID: {message.from_user.id}")

@dp.message(Command("pro"))
async def pro_command(message: types.Message):
    ensure_user(message.from_user)
    row = get_user(message.from_user.id)
    if is_pro(message.from_user.id):
        until = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(row["pro_until"]))
        await message.answer(f"💎 PRO faol.\nTugash vaqti: {until}")
    else:
        await message.answer("💎 Sizda hozir PRO obuna yo‘q.")

@dp.message(Command("history"))
async def history_command(message: types.Message):
    uid = message.from_user.id
    with db() as c:
        rows = c.execute("SELECT platform,kind,result,created_at FROM downloads WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
    if not rows:
        await message.answer("Hali yuklab olishlar tarixi yo‘q.")
        return
    lines = ["🗂 Oxirgi yuklashlar:"]
    for r in rows:
        stamp = time.strftime("%d.%m %H:%M", time.localtime(r["created_at"]))
        lines.append(f"• {r['platform']} | {r['kind']} | {r['result']} | {stamp}")
    await message.answer("\n".join(lines))

@dp.message(Command("stats"))
async def stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(tr(message.from_user.id, "not_admin"))
        return
    with db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        downloads = c.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    await message.answer(f"📊 SaverBot\nFoydalanuvchilar: {users}\nYuklashlar: {downloads}")

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

@dp.callback_query(F.data == "language")
async def language_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O‘zbekcha", callback_data="lang:uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ])
    await call.message.answer(tr(call.from_user.id, "choose_lang"), reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("lang:"))
async def set_language(call: types.CallbackQuery):
    code = call.data.split(":", 1)[1]
    if code not in LANGS:
        await call.answer()
        return
    with db() as c:
        c.execute("UPDATE users SET lang=?,language_selected=1 WHERE user_id=?", (code, call.from_user.id))
    await call.message.answer(tr(call.from_user.id, "welcome"), reply_markup=main_keyboard(call.from_user.id))
    await call.answer("OK")

async def command_download(message: types.Message, kind: str):
    ensure_user(message.from_user)
    uid = message.from_user.id
    if not await require_subscription(message, uid):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(f"Foydalanish: /{'video' if kind == 'video' else 'mp3'} https://...")
        return
    url = parts[1].strip()
    platform = platform_for(url)
    if not platform:
        await message.answer(tr(uid, "bad_url"))
        return
    if uid in active_tasks:
        await message.answer("Sizda yuklash jarayoni allaqachon bor.")
        return
    active_tasks[uid] = asyncio.create_task(do_download(message, uid, {"url": url, "platform": platform, "quality": "best"}, kind))

@dp.message(Command("video"))
async def video_command(message: types.Message):
    await command_download(message, "video")

@dp.message(Command("mp3"))
async def mp3_command(message: types.Message):
    await command_download(message, "audio")

@dp.message(Command("quality"))
async def quality_command(message: types.Message):
    ensure_user(message.from_user)
    if not await require_subscription(message, message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or parts[1] not in {"360", "480", "720", "1080", "best"}:
        await message.answer("Foydalanish: /quality 720 https://youtube.com/...")
        return
    url, quality = parts[2].strip(), parts[1]
    platform = platform_for(url)
    if not platform:
        await message.answer(tr(message.from_user.id, "bad_url"))
        return
    uid = message.from_user.id
    if uid in active_tasks:
        await message.answer("Sizda yuklash jarayoni allaqachon bor.")
        return
    active_tasks[uid] = asyncio.create_task(do_download(message, uid, {"url": url, "platform": platform, "quality": quality}, "video"))

@dp.message(F.text)
async def receive_text(message: types.Message):
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    ensure_user(message.from_user)
    uid = message.from_user.id
    if not await require_subscription(message, uid):
        return
    url = text.split()[0] if text else ""
    platform = platform_for(url)
    if not platform:
        await message.answer("Havolani yuboring yoki /help buyrug‘idan foydalaning.")
        return
    pending[uid] = {"url": url, "platform": platform, "quality": "best"}
    await message.answer(tr(uid, "choose"), reply_markup=choices_keyboard(uid))

@dp.callback_query(F.data == "quality")
async def quality_menu(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid not in pending:
        await call.answer("Avval havola yuboring.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="360p", callback_data="q:360"), InlineKeyboardButton(text="480p", callback_data="q:480")],
        [InlineKeyboardButton(text="720p", callback_data="q:720"), InlineKeyboardButton(text="1080p", callback_data="q:1080")],
        [InlineKeyboardButton(text="Eng yaxshi", callback_data="q:best")]
    ])
    await call.message.answer(tr(uid, "quality_note"), reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("q:"))
async def set_quality(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid in pending:
        pending[uid]["quality"] = call.data.split(":", 1)[1]
        await call.message.answer("✅ Sifat tanlandi. Endi Video yoki MP3 tugmasini bosing.", reply_markup=choices_keyboard(uid))
    await call.answer()

@dp.callback_query(F.data.startswith("kind:"))
async def choose_kind(call: types.CallbackQuery):
    uid = call.from_user.id
    if not await require_subscription(call, uid):
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
    active_tasks[uid] = asyncio.create_task(do_download(call.message, uid, item.copy(), kind))
    pending.pop(uid, None)
    await call.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_download(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid in active_tasks:
        cancel_flags.add(uid)
        await call.answer("Bekor qilish so‘rovi yuborildi.")
    else:
        pending.pop(uid, None)
        await call.answer("Faol yuklash yo‘q.")

async def safe_edit(message, text):
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        pass
    except Exception:
        log.exception("Could not edit status message")

async def do_download(message, uid, item, kind):
    url, platform, quality = item["url"], item["platform"], item["quality"]
    status = await message.answer(tr(uid, "working"), reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "cancel"), callback_data="cancel")]]
    ))
    output_path = None
    loop = asyncio.get_running_loop()
    last_edit = 0

    def hook(data):
        nonlocal last_edit
        if uid in cancel_flags:
            raise RuntimeError("Download cancelled")
        now = time.time()
        if data.get("status") == "downloading" and now - last_edit > 3:
            last_edit = now
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            got = data.get("downloaded_bytes") or 0
            pct = int(got * 100 / total) if total else 0
            asyncio.run_coroutine_threadsafe(safe_edit(status, f"⏳ {platform}: {pct}%"), loop)

    def run_ytdlp():
        prefix = f"{uid}_%(id)s.%(ext)s"
        fmt = "bestaudio/best" if kind == "audio" else (
            f"best[height<={quality}][ext=mp4]/best[height<={quality}]/best"
            if quality != "best" else "best[ext=mp4]/best"
        )
        opts = {
            "outtmpl": str(DOWNLOAD_DIR / prefix),
            "format": fmt,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 25,
            "retries": 2,
            "fragment_retries": 2,
            "max_filesize": MAX_DOWNLOAD_MB * 1024 * 1024,
            "progress_hooks": [hook],
        }
        if kind == "audio":
            opts.update({
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            })
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = Path(ydl.prepare_filename(info))
            if kind == "audio":
                filename = filename.with_suffix(".mp3")
            return filename

    try:
        output_path = await asyncio.to_thread(run_ytdlp)
        if uid in cancel_flags:
            raise asyncio.CancelledError()
        if not output_path.exists():
            candidates = sorted(DOWNLOAD_DIR.glob(f"{uid}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                output_path = candidates[0]
        if not output_path or not output_path.exists():
            raise FileNotFoundError("Downloaded file not found")
        size_mb = output_path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_DOWNLOAD_MB:
            raise ValueError("FILE_TOO_LARGE")
        await safe_edit(status, tr(uid, "sending"))
        if kind == "audio":
            await message.answer_audio(FSInputFile(output_path), caption=f"🎵 {platform} MP3")
        else:
            try:
                await message.answer_video(FSInputFile(output_path), caption=f"✅ {platform} video")
            except Exception:
                await message.answer_document(FSInputFile(output_path), caption=f"📁 {platform} video")
        await safe_edit(status, "✅ Tayyor!")
        add_history(uid, url, platform, kind, "ok")
    except asyncio.CancelledError:
        await safe_edit(status, tr(uid, "cancelled"))
        add_history(uid, url, platform, kind, "cancelled")
    except Exception as exc:
        err = str(exc).lower()
        log.exception("Download failed for user %s", uid)
        if "sign in to confirm" in err or "not a bot" in err or "confirm you're not a bot" in err:
            user_msg = tr(uid, "yt_blocked")
        elif "file_too_large" in err or "maximum file size" in err:
            user_msg = tr(uid, "too_large")
        elif "ffmpeg" in err:
            user_msg = "⚠️ MP3 konvertatsiyasi uchun FFmpeg kerak. Railway deploy sozlamalarida FFmpeg mavjudligini tekshiring."
        else:
            user_msg = tr(uid, "failed")
        await safe_edit(status, user_msg)
        add_history(uid, url, platform, kind, "error")
    finally:
        cancel_flags.discard(uid)
        active_tasks.pop(uid, None)
        for p in DOWNLOAD_DIR.glob(f"{uid}_*"):
            try:
                p.unlink()
            except OSError:
                pass

@dp.callback_query(F.data == "admin")
async def admin_menu(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    with db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        downloads = c.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    await call.message.answer(f"🛠 Admin panel\n👥 Foydalanuvchilar: {users}\n📥 Yuklashlar: {downloads}\n/stats")
    await call.answer()

async def main():
    init_db()
    log.info("SaverBot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

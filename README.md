# SaverBot

Telegram downloader for video or MP3 from websites supported by `yt-dlp` (hundreds of sites, but not literally every website). Includes mandatory subscription to `@CyberSecurity_full_course`, quality choices, cancellation and language options. Download-history UI and PRO/subscription system are removed. Existing SQLite data is left intact; the old history table is not used.

## Windows PowerShell

```powershell
cd "C:\path\to\SaverBot"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:BOT_TOKEN="YOUR_NEW_BOT_TOKEN"
$env:ADMIN_IDS="YOUR_TELEGRAM_USER_ID"
$env:REQUIRED_CHANNEL="@CyberSecurity_full_course"
python bot.py
```

## Mandatory subscription setup

1. Make sure the public channel username is exactly `@CyberSecurity_full_course`.
2. Add the bot as a **channel administrator** so Telegram can check membership.
3. Users run `/start`, join via the button, then press **Obunani tekshirish** or send `/checksub`.

If Telegram cannot verify membership, check the channel username and bot permissions.

## User commands

- `/start` — start and subscription gate.
- `/checksub` — verify channel membership.
- `/help` — command list.
- `/video URL` — download video directly.
- `/mp3 URL` — extract MP3 (requires FFmpeg on the server).
- `/quality 720 URL` — download video at selected quality (`360`, `480`, `720`, `1080`, `best`).
- `/language` — select interface language.
- `/id` — show Telegram numeric ID.

Or send a supported URL and choose Video/MP3 from inline buttons.

## Admin

Set `ADMIN_IDS` to comma-separated numeric Telegram IDs. `/stats` displays the user count.

## Notes

- `yt-dlp` supports hundreds of sites, but no downloader can promise every website; some sites require cookies, login, or are blocked.
- MP3 extraction requires FFmpeg installed and available on PATH.
- `MAX_DOWNLOAD_MB` defaults to 48 MB. Telegram upload limits apply.
- Keep your bot token private; revoke it through BotFather if exposed.

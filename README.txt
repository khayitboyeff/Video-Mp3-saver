SaverBot - corrected starter files

1) Install Python 3.12+.
2) In PowerShell, open this folder and run:
   python -m pip install -r requirements.txt
3) Set your Telegram bot token (never post it publicly):
   $env:BOT_TOKEN="YOUR_NEW_BOT_TOKEN"
4) Optional admin Telegram IDs:
   $env:ADMIN_IDS="123456789"
5) Optional required channel (default @CyberSecurity_full_course):
   $env:REQUIRED_CHANNEL="@CyberSecurity_full_course"
6) Run:
   python bot.py

Important:
- Add the bot as an administrator in the required channel so membership checks can work.
- FFmpeg must be installed and available on PATH for MP3 conversion and merging separate video/audio streams.
- MAX_DOWNLOAD_MB limits download size; it does NOT change Telegram's upload limit. Large files may fail to send through the standard Bot API.
- Download only content you own or have permission to download and follow each platform's terms.

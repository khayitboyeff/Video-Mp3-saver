# SaverBot — tuzatilgan versiya

## Railway Variables
- `BOT_TOKEN` — Telegram bot tokeni (maxfiy saqlang).
- `ADMIN_IDS` — admin Telegram ID'lari, masalan `123456789`.
- `REQUIRED_CHANNEL` — kanal username'i, masalan `@CyberSecurity_full_course`.
- `CHANNEL_URL` — ixtiyoriy obuna havolasi.
- `MAX_DOWNLOAD_MB` — maksimal fayl hajmi; standart 45 MB.

## Railway sozlamalari
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- `requirements.txt` bilan qayta deploy qiling.
- Majburiy obunani tekshirish uchun botni kanalga admin qilib qo'ying.
- MP3 konvertatsiyasi uchun muhitda FFmpeg bo'lishi kerak. FFmpeg yo'q bo'lsa, video yuklash ishlashi mumkin, audio konvertatsiyasi esa ishlamasligi mumkin.

## Muhim
YouTube ba'zi videolarda login yoki bot-tekshiruv talab qiladi. Kod bunday xatoni ushlaydi va botni yiqitmaydi, lekin bu cheklovni chetlab o'tishni kafolatlamaydi.
Fayllar vaqtinchalik `downloads/` ichiga tushadi va yuborilgach o'chiriladi. SQLite bazani doimiy saqlamoqchi bo'lsangiz, Railway persistent volume ulang va `SAVERBOT_DB` ni volume ichidagi yo'lga belgilang.

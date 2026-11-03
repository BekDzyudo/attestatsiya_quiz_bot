# Attestatsiya quiz bot

Har kuni 09:00–23:30 (Toshkent) oralig'ida har 10 daqiqada `quizzes.json` dagi navbatdagi savolni Telegram guruhiga quiz qilib yuboradi.

- `quizzes.json` — savollar banki (savol, 4 variant, to'g'ri javob raqami, izoh)
- `state.json` — keyingi yuboriladigan savol raqami (`next`, 0 dan boshlanadi)
- `send.py` — yuboruvchi skript
- `.github/workflows/quiz.yml` — jadval

Sozlash: repo **Settings → Secrets and variables → Actions → New repository secret**, nomi `TELEGRAM_TOKEN`, qiymati — bot tokeni.

Qo'lda sinash: **Actions → Attestatsiya quiz → Run workflow**.

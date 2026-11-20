# English Runner — with Google Login

Cyberpunk vocabulary/grammar runner game, gated behind Google OAuth login.
Scores are saved per user in SQLite (`app.db`, created automatically).

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. `.env` is already filled in with your Google OAuth credentials. If you
   ever need to change them, edit:
   ```
   FLASK_SECRET_KEY=...
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```

3. In the Google Cloud Console, under your OAuth Client's
   **Authorized redirect URIs**, make sure this is added:
   ```
   http://localhost:5000/authorize
   ```
   (add your production URL + `/authorize` too, once you deploy)

4. Run it:
   ```bash
   python app.py
   ```
   Open https://wordrunner.onrender.com/

## How it works

- `/` shows a Google login button if you're not logged in.
- After logging in, a row is created for you in the `users` table
  (SQLite) and the game loads.
- `/api/question`, `/api/check`, `/api/save-score` all require login.
- On game over, the run's score is POSTed to `/api/save-score` and
  added to your all-time total, shown in the top bar.
- `/logout` clears your session.

## Files

```
app.py                # Flask app: OAuth + SQLite users + game API
requirements.txt
.env                  # Your Google OAuth credentials + Flask secret key
templates/index.html  # Login gate OR game UI, depending on session
static/style.css      # English Runner theme + auth bar styling
static/script.js      # Game loop; posts score to /api/save-score on game over
```

## Admin panel

`/admin` — faqat `ADMIN_EMAILS` (env, vergul bilan ajratilgan; standart: `murodtojievuz@gmail.com`)
ro'yxatidagi Google akkaunt kira oladi. Boshqalar uchun sahifa 404 qaytaradi.

- **Dashboard** — jami o'yinchilar, bugungi faollar, o'rtacha ball, eng ko'p o'ynalgan bosqich
- **Foydalanuvchilar** — qidirish, ballni nolga tushirish, bosqichni o'zgartirish, o'chirish (+ bloklash)
- **Savollar** — English Runner savollarini qo'shish / tahrirlash / o'chirish (DB `questions` jadvali)
- **Lug'at** — so'z juftliklari, bosqich bo'yicha filter (DB `vocab` jadvali)

Eslatma: savollar va lug'at birinchi ishga tushishda bir marta bazaga ko'chiriladi
(`meta` jadvali bayrog'i), shuning uchun admin o'chirgan narsalar qayta tiklanmaydi.

Files: `admin.py`, `templates/admin.html`, `static/admin.css`, `static/admin.js`

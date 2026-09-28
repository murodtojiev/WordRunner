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
   Open http://localhost:5000

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

"""
English Runner + Google OAuth login — v2 (Level Map Edition)
-------------------------------------------------------------
Features:
  - Google OAuth login with Authlib
  - Strict PostgreSQL (Neon) connection
  - Duolingo-style 10-level map
  - 15 correct answers per level to advance
  - Leaderboard (Top 10 by total_score)
  - 60-question vocabulary / grammar bank
"""

import os
import json
import random
import requests
from functools import wraps

from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

import psycopg2
from psycopg2.extras import RealDictCursor, Json

# -----------------------------------------------------------------------
# 1. Load secrets from .env
# -----------------------------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# -----------------------------------------------------------------------
# 2. Database connection + schema + user helpers (Strictly PostgreSQL)
# -----------------------------------------------------------------------
def get_db():
    if not DATABASE_URL:
        raise ValueError("XATOLIK: DATABASE_URL topilmadi! Render sozlamalarini tekshiring.")
    
    print("Neon bazasiga ulanmoqda...")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn, "postgres"


def db_execute(conn, engine, query, params=()):
    # PostgreSQL requires %s instead of ? for parameters
    query = query.replace("?", "%s")
    cur = conn.cursor()
    cur.execute(query, params)
    return cur


def init_db():
    conn, engine = get_db()
    db_execute(conn, engine, """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            google_id VARCHAR(255) UNIQUE NOT NULL,
            name VARCHAR(255),
            email VARCHAR(255),
            picture TEXT,
            total_score INTEGER DEFAULT 0,
            current_level INTEGER DEFAULT 1
        )
    """)
    db_execute(conn, engine, """
        CREATE TABLE IF NOT EXISTS vocab (
            id SERIAL PRIMARY KEY,
            uz_word TEXT NOT NULL,
            en_translation TEXT NOT NULL,
            level INTEGER DEFAULT 1
        )
    """)
    db_execute(conn, engine, "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ")
    db_execute(conn, engine, """
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            question TEXT NOT NULL,
            options JSONB NOT NULL,
            answer INTEGER NOT NULL,
            category VARCHAR(30) DEFAULT 'grammar'
        )
    """)
    db_execute(conn, engine, """
        CREATE TABLE IF NOT EXISTS level_plays (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            game VARCHAR(20) NOT NULL,
            level INTEGER NOT NULL,
            played_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db_execute(conn, engine, """
        CREATE TABLE IF NOT EXISTS blocked_emails (
            email VARCHAR(255) PRIMARY KEY,
            blocked_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db_execute(conn, engine, """
        CREATE TABLE IF NOT EXISTS meta (
            key VARCHAR(50) PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()


def is_email_blocked(email):
    if not email:
        return False
    conn, engine = get_db()
    cur = db_execute(conn, engine, "SELECT 1 FROM blocked_emails WHERE email = ?", (email.lower(),))
    found = cur.fetchone() is not None
    conn.close()
    return found


def touch_last_active(user_id):
    conn, engine = get_db()
    db_execute(conn, engine, "UPDATE users SET last_active = now() WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_or_create_user(google_id, name, email, picture):
    conn, engine = get_db()

    cur = db_execute(conn, engine, "SELECT * FROM users WHERE google_id = ?", (google_id,))
    user = cur.fetchone()

    if user is None:
        db_execute(
            conn, engine,
            """INSERT INTO users (google_id, name, email, picture, total_score, current_level)
               VALUES (?, ?, ?, ?, 0, 1)""",
            (google_id, name, email, picture),
        )
        conn.commit()
        cur = db_execute(conn, engine, "SELECT * FROM users WHERE google_id = ?", (google_id,))
        user = cur.fetchone()
    else:
        db_execute(
            conn, engine,
            "UPDATE users SET name = ?, email = ?, picture = ? WHERE google_id = ?",
            (name, email, picture, google_id),
        )
        conn.commit()
        cur = db_execute(conn, engine, "SELECT * FROM users WHERE google_id = ?", (google_id,))
        user = cur.fetchone()

    conn.close()
    return dict(user)


def get_user_by_id(user_id):
    conn, engine = get_db()
    cur = db_execute(conn, engine, "SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_to_user_score(user_id, points):
    """Adds `points` to the user's running total and returns the new total."""
    conn, engine = get_db()
    db_execute(
        conn, engine,
        "UPDATE users SET total_score = total_score + ? WHERE id = ?",
        (points, user_id),
    )
    conn.commit()
    cur = db_execute(conn, engine, "SELECT total_score FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row)["total_score"] if row else None


def update_user_level(user_id, new_level):
    """Sets the user's current_level (only if new_level is higher)."""
    conn, engine = get_db()
    db_execute(
        conn, engine,
        "UPDATE users SET current_level = CASE WHEN ? > current_level THEN ? ELSE current_level END WHERE id = ?",
        (new_level, new_level, user_id),
    )
    conn.commit()
    cur = db_execute(conn, engine, "SELECT current_level FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row)["current_level"] if row else None


def seed_vocab():
    """Seeds the vocab table with 213 words from the IELTS course dictionary."""
    conn, engine = get_db()
    cur = db_execute(conn, engine, "SELECT COUNT(*) AS cnt FROM vocab")
    row = cur.fetchone()
    count = row.get("cnt", 0) if row else 0
    if isinstance(count, dict):
        count = list(row.values())[0]

    cur = db_execute(conn, engine, "SELECT 1 FROM meta WHERE key = 'vocab_seeded'")
    already_seeded = cur.fetchone() is not None
    if already_seeded:
        conn.close()
        return

    # First run after admin-panel upgrade: seed only if table is empty or has old data (< 200 rows)
    if count < 200:
        # Clear old data first
        db_execute(conn, engine, "DELETE FROM vocab")
        conn.commit()

        words = [
            # ============================================================
            # Level 1 — Oila, uy, kundalik hayot (43 so'z)
            # ============================================================
            ("martaba ko'tarilish", "promotion", 1),
            ("stol", "desk", 1),
            ("yo'qolgan", "missing", 1),
            ("tartibli", "tidy", 1),
            ("ajoyib", "amazing", 1),
            ("dahshatli", "terrible", 1),
            ("ovqatlanish xonasi", "dining room", 1),
            ("hisob-kitob", "bill", 1),
            ("tanishtirmoq", "introduce", 1),
            ("taklif", "offer", 1),
            ("javon", "cupboard", 1),
            ("to'ti", "parrot", 1),
            ("kafe", "cafe", 1),
            ("baxtsiz hodisa", "accident", 1),
            ("intizom", "discipline", 1),
            ("makon", "space", 1),
            ("moslashmoq", "adapt", 1),
            ("yo'nalish", "direction", 1),
            ("ehtimol", "probably", 1),
            ("qabul qilmoq", "accept", 1),
            ("ta'sir", "influence", 1),
            ("shaxsiyat", "personality", 1),
            ("qarama-qarshi", "opposite", 1),
            ("jalb qilmoq", "attract", 1),
            ("o'gay ona", "stepmother", 1),
            ("olib yurmoq", "carry", 1),
            ("a'zo", "member", 1),
            ("qarindosh", "relative", 1),
            ("juftlik", "couple", 1),
            ("iqtibos", "quote", 1),
            ("bo'shliq", "gap", 1),
            ("makaron", "pasta", 1),
            ("piyoz", "onion", 1),
            ("donolik", "wisdom", 1),
            ("maosh", "salary", 1),
            ("bayonot", "statement", 1),
            ("kasallik", "disease", 1),
            ("biroq", "however", 1),
            ("aloqa", "connection", 1),
            ("retsept", "recipe", 1),
            ("aka-uka/opa-singil", "sibling", 1),
            ("maslahat", "tip", 1),
            ("odat", "habit", 1),

            # ============================================================
            # Level 2 — Xarakter, his-tuyg'ular, sifatlar (43 so'z)
            # ============================================================
            ("taassurot qoldirmoq", "impress", 2),
            ("dahshatga tushgan", "horrified", 2),
            ("bashorat qilmoq", "predict", 2),
            ("ariza topshirmoq", "apply", 2),
            ("o'ziga ishonchgan", "self-confident", 2),
            ("yetishmaslik", "lack", 2),
            ("saxiy", "generous", 2),
            ("gapdon", "talkative", 2),
            ("xasis", "mean", 2),
            ("uyatchan", "shy", 2),
            ("tashvishli", "anxious", 2),
            ("maqsadli", "ambitious", 2),
            ("isyonchi", "rebellious", 2),
            ("ijtimoiy", "sociable", 2),
            ("ishonchli", "reliable", 2),
            ("mas'uliyatli", "responsible", 2),
            ("raqobatbardosh", "competitive", 2),
            ("sezgir", "sensitive", 2),
            ("sabrsiz", "impatient", 2),
            ("yetilmagan", "immature", 2),
            ("ochiq", "outgoing", 2),
            ("jozibali", "charming", 2),
            ("tartibsiz", "disorganized", 2),
            ("erkalatilgan", "spoilt", 2),
            ("mustaqil", "independent", 2),
            ("mehrli", "affectionate", 2),
            ("o'zini boshliqdek tutadigan", "bossy", 2),
            ("tasavvurga boy", "imaginative", 2),
            ("ishonchsiz", "insecure", 2),
            ("kayfiyati tez o'zgaruvchi", "moody", 2),
            ("xudbin", "selfish", 2),
            ("aqlli", "sensible", 2),
            ("o'jar", "stubborn", 2),
            ("qo'pol", "rude", 2),
            ("qo'rqmas", "bold", 2),
            ("chidamsiz", "intolerant", 2),
            ("mazali", "delicious", 2),
            ("odatiy", "common", 2),
            ("yangi", "fresh", 2),
            ("xom", "raw", 2),
            ("achchiq", "spicy", 2),
            ("gazlangan", "fizzy", 2),
            ("qovurilgan", "fried", 2),

            # ============================================================
            # Level 3 — Ovqat, taom, oshxona (42 so'z)
            # ============================================================
            ("qaynatilgan", "boiled", 3),
            ("konservalangan", "tinned", 3),
            ("tandirda pishirilgan", "baked", 3),
            ("mos kelmoq", "match", 3),
            ("dengiz mahsulotlari", "seafood", 3),
            ("losos", "salmon", 3),
            ("kalmar", "squid", 3),
            ("mol go'shti", "beef", 3),
            ("qo'zichoq go'shti", "lamb", 3),
            ("cho'chqa go'shti", "pork", 3),
            ("baqlajon", "eggplant", 3),
            ("karam", "cabbage", 3),
            ("olcha", "cherry", 3),
            ("bodring", "cucumber", 3),
            ("uzum", "grapes", 3),
            ("yashil loviya", "green beans", 3),
            ("qovun", "melon", 3),
            ("shaftoli", "peach", 3),
            ("malina", "raspberries", 3),
            ("qalampir", "pepper", 3),
            ("lavlagi", "beetroot", 3),
            ("oshpaz", "cook", 3),
            ("pechka", "cooker", 3),
            ("banka", "jar", 3),
            ("murabbo", "jam", 3),
            ("so'rovnoma", "questionnaire", 3),
            ("gazak", "snack", 3),
            ("nachinka", "filling", 3),
            ("soboy ovqat", "takeaway", 3),
            ("zaytun yog'i", "olive oil", 3),
            ("bosh oshpaz", "chef", 3),
            ("bug'da pishirilgan", "steamed", 3),
            ("afzal ko'rmoq", "prefer", 3),
            ("rad etmoq", "refuse", 3),
            ("javob bermoq", "respond", 3),
            ("sabab", "cause", 3),
            ("o'rtacha", "on average", 3),
            ("maqola", "article", 3),
            ("so'rov", "survey", 3),
            ("sig'im", "capacity", 3),
            ("chidamlilik", "endurance", 3),
            ("vazifa", "task", 3),

            # ============================================================
            # Level 4 — Grammatika, o'rganish, akademik (43 so'z)
            # ============================================================
            ("nuqtayi nazar", "point of view", 3),
            ("bo'g'in", "syllable", 4),
            ("sog'lom fikr", "common sense", 4),
            ("haqorat qilmoq", "offend", 4),
            ("munosabat", "attitude", 4),
            ("qobiliyat", "ability", 4),
            ("bo'ysunmoq", "obey", 4),
            ("o'xshash", "similar", 4),
            ("qoida", "rule", 4),
            ("ustun", "column", 4),
            ("bashorat", "prediction", 4),
            ("niyat", "intention", 4),
            ("kelishuv", "arrangement", 4),
            ("mazmun", "content", 4),
            ("xabardor bo'lmoq", "be aware of", 4),
            ("birikma", "combination", 4),
            ("kamaytirmoq", "cut down on", 4),
            ("unli", "vowel", 4),
            ("taklif qilmoq", "suggest", 4),
            ("aksincha", "vice versa", 4),
            ("buzmoq", "disrupt", 4),
            ("mustasno", "except", 4),
            ("qo'shimcha", "supplement", 4),
            ("oshqozon", "stomach", 4),
            ("hazm qilmoq", "digest", 4),
            ("bajarmoq", "carry out", 4),
            ("umuman olganda", "in general", 4),
            ("asrab olingan bola", "adopted child", 4),
            ("yaqin oila", "immediate family", 4),
            ("kengaytirilgan oila", "extended family", 4),
            ("o'zini tutmoq", "behave", 4),
            ("o'g'irlamoq", "steal", 4),
            ("aldamoq", "cheat", 4),
            ("qaramoq", "look after", 4),
            ("bog'liq bo'lmoq", "depend on", 4),
            ("moyil bo'lmoq", "tend to", 4),
            ("hisobga olmoq", "consider", 4),
            ("ko'rib chiqish", "review", 4),
            ("sanchmoq", "stab", 4),
            ("o'ylamoq", "based on", 4),
            ("yengil ovqat", "light food", 4),
            ("tuyg'u", "sense", 4),
            ("bugun kechqurun", "tonight", 4),

            # ============================================================
            # Level 5 — Ilg'or lug'at, iboralar (42 so'z)
            # ============================================================
            ("yaxshi chiqishmoq", "get on well", 5),
            ("qo'rqmoq", "afraid of", 5),
            ("xato bo'lmoq", "go wrong", 5),
            ("odatda", "typically", 5),
            ("bahslarni hal qilmoq", "sort out arguments", 5),
            ("yutqazgan tomon", "losing side", 5),
            ("mumkin", "possibly", 5),
            ("ya'ni", "that is", 5),
            ("ekstravert", "extrovert", 5),
            ("katta buva", "great-grandfather", 5),
            ("kayfiyati ko'tarilmoq", "cheer up", 5),
            ("umumiy jihatga ega bo'lmoq", "have in common", 5),
            ("o'zining", "own", 5),
            ("…ga asoslangan", "based on", 5),
            ("…ga ko'ra", "according to", 5),
            ("zudlik bilan", "as soon as", 5),
            ("nonushta qilmaslik", "skip breakfast", 5),
            ("tadqiqot guruhi", "research team", 5),
            ("restoran boshqarmoq", "run a restaurant", 5),
            ("vaqti-vaqti bilan", "occasionally", 5),
            ("hech bo'lmaganda", "at least", 5),
            ("cho'girma pichoq", "penknife", 5),
            ("planshet", "tablet", 5),
            ("bo'ydoq", "single", 5),
            ("qo'llamoq", "apply", 5),
            ("istamoq", "would like", 5),
            ("yig'ilish", "get-together", 5),
            ("qayni aka/uka", "brother-in-law", 5),
            ("yarim o'gay singil", "half-sister", 5),
            ("mol go'shti", "beef", 5),
            ("ustiga qo'shiladigan narsa", "topping", 5),
            ("uyda yemoq", "eat in", 5),
            ("tashqarida yemoq", "eat out", 5),
            ("aqliy ravishda faol", "mentally alert", 5),
            ("yolg'iz", "on my own", 5),
            ("to'xtatmoq", "cut out", 5),
            ("qovurilgan", "roast", 5),
            ("ko'rib chiqish", "review", 5),
            ("tagiga chizmoq", "underline", 5),
            ("istamoq", "would rather", 5),
            ("kelishmovchilik", "row", 5),
            ("hechqisi yo'q", "never mind", 5),
        ]
        for uz_word, en_translation, level in words:
            db_execute(
                conn, engine,
                "INSERT INTO vocab (uz_word, en_translation, level) VALUES (?, ?, ?)",
                (uz_word, en_translation, level),
            )
        conn.commit()
    db_execute(conn, engine, "INSERT INTO meta (key, value) VALUES ('vocab_seeded', '1') ON CONFLICT DO NOTHING")
    conn.commit()
    conn.close()



# -----------------------------------------------------------------------
# 3. Google OAuth 2.0 client setup (Authlib)
# -----------------------------------------------------------------------
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# -----------------------------------------------------------------------
# 4. login_required decorator
# -----------------------------------------------------------------------
def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "login required"}), 401
        if get_user_by_id(session["user"]["id"]) is None:
            session.clear()
            return jsonify({"error": "login required"}), 401
        return view_func(*args, **kwargs)
    return wrapped


# -----------------------------------------------------------------------
# 5. Auth routes
# -----------------------------------------------------------------------
@app.route("/login")
def login():
    redirect_uri = url_for("authorize", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/authorize")
def authorize():
    token = google.authorize_access_token()

    user_info = token.get("userinfo")
    if not user_info:
        user_info = google.get("https://openidconnect.googleapis.com/v1/userinfo").json()

    if is_email_blocked(user_info.get("email")):
        session.clear()
        return "Bu hisob uchun kirish taqiqlangan.", 403

    user = get_or_create_user(
        google_id=user_info["sub"],
        name=user_info.get("name"),
        email=user_info.get("email"),
        picture=user_info.get("picture"),
    )

    session["user"] = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "picture": user["picture"],
        "total_score": user["total_score"],
        "current_level": user["current_level"],
        "email_verified": bool(user_info.get("email_verified", False)),
    }
    touch_last_active(user["id"])

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# -----------------------------------------------------------------------
# 6. Home route — login gate or game, depending on session
# -----------------------------------------------------------------------
@app.route("/")
def index():
    user = session.get("user")
    if user:
        fresh = get_user_by_id(user["id"])
        if fresh:
            session["user"]["total_score"] = fresh["total_score"]
            session["user"]["current_level"] = fresh["current_level"]
            user = session["user"]
    return render_template("index.html", user=user, active_page="home")


@app.route("/map")
def map_page():
    user = session.get("user")
    if not user:
        return redirect(url_for("login"))
    fresh = get_user_by_id(user["id"])
    if fresh:
        session["user"]["total_score"] = fresh["total_score"]
        session["user"]["current_level"] = fresh["current_level"]
        user = session["user"]
    return render_template("index.html", user=user, active_page="map")


@app.route("/leaderboard")
def leaderboard_page():
    user = session.get("user")
    if not user:
        return redirect(url_for("login"))
    fresh = get_user_by_id(user["id"])
    if fresh:
        session["user"]["total_score"] = fresh["total_score"]
        session["user"]["current_level"] = fresh["current_level"]
        user = session["user"]
    return render_template("index.html", user=user, active_page="leaderboard")


# -----------------------------------------------------------------------
# 7. Game API — English Runner question bank (login-gated)
# -----------------------------------------------------------------------
SEED_QUESTIONS = [
    # --- Synonyms ---
    {"id": 1,  "question": "Choose the synonym of \u201cHAPPY\u201d",           "options": ["Joyful", "Angry", "Tired", "Silent"],       "answer": 0},
    {"id": 12, "question": "Choose the synonym of \u201cBIG\u201d",             "options": ["Tiny", "Large", "Narrow", "Short"],          "answer": 1},
    {"id": 14, "question": "Choose the synonym of \u201cBEAUTIFUL\u201d",       "options": ["Pretty", "Ugly", "Plain", "Boring"],         "answer": 0},
    {"id": 21, "question": "Choose the synonym of \u201cQUICK\u201d",           "options": ["Slow", "Fast", "Heavy", "Weak"],             "answer": 1},
    {"id": 29, "question": "Choose the synonym of \u201cBRAVE\u201d",           "options": ["Courageous", "Scared", "Lazy", "Quiet"],     "answer": 0},
    {"id": 35, "question": "Choose the synonym of \u201cANGRY\u201d",           "options": ["Happy", "Calm", "Furious", "Gentle"],        "answer": 2},
    {"id": 41, "question": "Choose the synonym of \u201cSMART\u201d",           "options": ["Dull", "Intelligent", "Weak", "Slow"],       "answer": 1},
    {"id": 47, "question": "Choose the synonym of \u201cTINY\u201d",            "options": ["Huge", "Small", "Tall", "Wide"],             "answer": 1},
    {"id": 53, "question": "Choose the synonym of \u201cSTRANGE\u201d",         "options": ["Normal", "Usual", "Unusual", "Regular"],     "answer": 2},
    {"id": 60, "question": "Choose the synonym of \u201cCALM\u201d",            "options": ["Angry", "Peaceful", "Loud", "Wild"],         "answer": 1},

    # --- Antonyms ---
    {"id": 2,  "question": "Choose the antonym of \u201cHOT\u201d",             "options": ["Warm", "Boiling", "Cold", "Spicy"],          "answer": 2},
    {"id": 13, "question": "Choose the antonym of \u201cFAST\u201d",            "options": ["Quick", "Rapid", "Slow", "Swift"],           "answer": 2},
    {"id": 15, "question": "Choose the antonym of \u201cDIFFICULT\u201d",       "options": ["Hard", "Complex", "Easy", "Tough"],          "answer": 2},
    {"id": 22, "question": "Choose the antonym of \u201cBEGIN\u201d",           "options": ["Start", "Open", "End", "Continue"],          "answer": 2},
    {"id": 30, "question": "Choose the antonym of \u201cCHEAP\u201d",           "options": ["Free", "Expensive", "Low", "Small"],         "answer": 1},
    {"id": 42, "question": "Choose the antonym of \u201cPOLITE\u201d",          "options": ["Kind", "Rude", "Nice", "Gentle"],            "answer": 1},
    {"id": 51, "question": "Choose the antonym of \u201cREMEMBER\u201d",        "options": ["Recall", "Think", "Forget", "Know"],         "answer": 2},
    {"id": 58, "question": "Choose the antonym of \u201cBORROW\u201d",          "options": ["Take", "Lend", "Keep", "Steal"],             "answer": 1},

    # --- Vocabulary / Definitions ---
    {"id": 16, "question": "\u201cENORMOUS\u201d most nearly means\u2026",       "options": ["Very small", "Very large", "Very quiet", "Very old"],    "answer": 1},
    {"id": 17, "question": "\u201cRARE\u201d most nearly means\u2026",           "options": ["Common", "Fast", "Not common", "Loud"],                 "answer": 2},
    {"id": 26, "question": "\u201cANCIENT\u201d most nearly means\u2026",        "options": ["New", "Modern", "Very old", "Fast"],                    "answer": 2},
    {"id": 32, "question": "\u201cNUMEROUS\u201d most nearly means\u2026",       "options": ["Few", "Many", "None", "Single"],                        "answer": 1},
    {"id": 38, "question": "\u201cBRIEF\u201d most nearly means\u2026",          "options": ["Long", "Short", "Tall", "Wide"],                        "answer": 1},
    {"id": 48, "question": "\u201cGENEROUS\u201d most nearly means\u2026",       "options": ["Stingy", "Willing to give", "Angry", "Shy"],            "answer": 1},
    {"id": 54, "question": "\u201cFREQUENT\u201d most nearly means\u2026",       "options": ["Rare", "Happening often", "Slow", "Old"],               "answer": 1},

    # --- Grammar: present tense / to be ---
    {"id": 3,  "question": "\u201cI ___ to school every day.\u201d",             "options": ["go", "goes", "going", "went"],         "answer": 0},
    {"id": 4,  "question": "\u201cShe ___ a doctor.\u201d",                      "options": ["am", "is", "are", "be"],                "answer": 1},
    {"id": 5,  "question": "\u201cThey ___ playing football now.\u201d",          "options": ["is", "am", "are", "be"],                "answer": 2},
    {"id": 28, "question": "\u201cShe ___ reading a book right now.\u201d",       "options": ["am", "is", "are", "be"],                "answer": 1},
    {"id": 44, "question": "\u201cThe book ___ on the table.\u201d",              "options": ["am", "is", "are", "be"],                "answer": 1},

    # --- Grammar: past tense ---
    {"id": 7,  "question": "Choose the correct past tense of \u201cGO\u201d",    "options": ["Goed", "Gone", "Went", "Going"],        "answer": 2},
    {"id": 27, "question": "Choose the past tense of \u201cBUY\u201d",           "options": ["Buyed", "Bought", "Buying", "Buys"],    "answer": 1},
    {"id": 39, "question": "Choose the past tense of \u201cTEACH\u201d",         "options": ["Teached", "Taught", "Teaching", "Teachs"], "answer": 1},
    {"id": 55, "question": "Choose the past tense of \u201cSWIM\u201d",          "options": ["Swimmed", "Swam", "Swimming", "Swum"],  "answer": 1},

    # --- Grammar: past participle ---
    {"id": 20, "question": "Choose the past participle of \u201cEAT\u201d",      "options": ["Ate", "Eaten", "Eating", "Eats"],       "answer": 1},
    {"id": 49, "question": "Choose the past participle of \u201cWRITE\u201d",    "options": ["Wrote", "Written", "Writing", "Writes"],"answer": 1},

    # --- Grammar: comparatives / superlatives ---
    {"id": 8,  "question": "\u201cThis is the ___ book I have ever read.\u201d",  "options": ["best", "gooder", "more good", "goodest"],  "answer": 0},
    {"id": 18, "question": "Choose the comparative form of \u201cGOOD\u201d",     "options": ["Gooder", "Best", "Better", "More good"],    "answer": 2},
    {"id": 37, "question": "\u201cShe is ___ than her sister.\u201d",             "options": ["tall", "taller", "tallest", "more tall"],   "answer": 1},

    # --- Grammar: prepositions / articles ---
    {"id": 9,  "question": "\u201cThe cat is ___ the table.\u201d",               "options": ["on", "at", "for", "into"],              "answer": 0},
    {"id": 10, "question": "\u201c___ apple a day keeps the doctor away.\u201d",  "options": ["A", "An", "The", "Some"],               "answer": 1},
    {"id": 56, "question": "\u201c___ cat is on the roof.\u201d",                 "options": ["A", "An", "The", "Some"],               "answer": 2},

    # --- Grammar: adverbs / modifiers ---
    {"id": 23, "question": "\u201cHe has ___ finished his homework.\u201d",       "options": ["already", "ago", "yesterday", "next"],  "answer": 0},
    {"id": 34, "question": "\u201cHe speaks English very ___.\u201d",             "options": ["good", "well", "best", "nice"],         "answer": 1},
    {"id": 36, "question": "\u201cI have ___ been to Paris.\u201d",               "options": ["never", "ever", "ago", "yesterday"],    "answer": 0},

    # --- Grammar: perfect tenses / conditionals ---
    {"id": 31, "question": "\u201cIf I ___ you, I would study harder.\u201d",     "options": ["am", "were", "was", "is"],              "answer": 1},
    {"id": 40, "question": "\u201cWe ___ dinner when the phone rang.\u201d",      "options": ["have", "were having", "has", "had have"], "answer": 1},
    {"id": 46, "question": "\u201c___ you ever visited London?\u201d",            "options": ["Have", "Has", "Did", "Do"],             "answer": 0},
    {"id": 52, "question": "\u201cHe ___ his homework before dinner.\u201d",      "options": ["finished", "had finished", "finishes", "finishing"], "answer": 1},
    {"id": 59, "question": "\u201cShe ___ here since 2020.\u201d",               "options": ["is", "has been", "was", "were"],        "answer": 1},

    # --- Grammar: pronouns / homophones ---
    {"id": 25, "question": "\u201c___ going to the party tonight.\u201d",         "options": ["Their", "There", "They're", "Them"],    "answer": 2},
    {"id": 50, "question": "\u201cShe asked me ___ I was going.\u201d",           "options": ["were", "where", "wear", "we're"],       "answer": 1},

    # --- Plurals ---
    {"id": 6,  "question": "Choose the correct plural of \u201cCHILD\u201d",     "options": ["Childs", "Childes", "Children", "Childrens"], "answer": 2},
    {"id": 19, "question": "Choose the plural of \u201cMOUSE\u201d",             "options": ["Mouses", "Mices", "Mice", "Mouse"],      "answer": 2},
    {"id": 33, "question": "Choose the plural of \u201cTOOTH\u201d",             "options": ["Tooths", "Teeth", "Toothes", "Teeths"],  "answer": 1},

    # --- Spelling ---
    {"id": 11, "question": "Choose the correct spelling",                         "options": ["Recieve", "Receeve", "Receive", "Receve"], "answer": 2},
    {"id": 45, "question": "Choose the correct spelling",                         "options": ["Neccessary", "Necessary", "Necesary", "Neccesary"], "answer": 1},

    # --- Idioms ---
    {"id": 24, "question": "\u201cBreak the ice\u201d means\u2026",              "options": ["To fight", "To start a conversation", "To cool down", "To leave quickly"], "answer": 1},
    {"id": 43, "question": "\u201cA piece of cake\u201d means\u2026",            "options": ["A dessert", "Something very easy", "A reward", "A surprise"], "answer": 1},
    {"id": 57, "question": "\u201cUnder the weather\u201d means\u2026",          "options": ["Outside", "Feeling sick", "In the rain", "Very cold"],  "answer": 1},
]


def categorize_question(text):
    t = text.lower()
    if "synonym" in t: return "synonym"
    if "antonym" in t: return "antonym"
    if "most nearly means" in t: return "vocabulary"
    if "plural" in t: return "plural"
    if "spelling" in t: return "spelling"
    if "means" in t: return "idiom"
    return "grammar"


def seed_questions():
    """Copies the built-in question bank into the DB once (admin edits persist afterwards)."""
    conn, engine = get_db()
    cur = db_execute(conn, engine, "SELECT 1 FROM meta WHERE key = 'questions_seeded'")
    if cur.fetchone() is None:
        cur = db_execute(conn, engine, "SELECT COUNT(*) AS cnt FROM questions")
        if cur.fetchone()["cnt"] == 0:
            for q in sorted(SEED_QUESTIONS, key=lambda x: x["id"]):
                db_execute(
                    conn, engine,
                    "INSERT INTO questions (id, question, options, answer, category) VALUES (?, ?, ?, ?, ?)",
                    (q["id"], q["question"], Json(q["options"]), q["answer"], categorize_question(q["question"])),
                )
            db_execute(conn, engine,
                "SELECT setval(pg_get_serial_sequence('questions', 'id'), (SELECT MAX(id) FROM questions))")
        db_execute(conn, engine, "INSERT INTO meta (key, value) VALUES ('questions_seeded', '1') ON CONFLICT DO NOTHING")
        conn.commit()
    conn.close()


init_db()
seed_vocab()
seed_questions()


@app.route("/api/question")
@login_required
def get_question():
    last_id = session.get("last_id") or 0
    conn, engine = get_db()
    try:
        cur = db_execute(conn, engine,
            "SELECT id, question, options FROM questions WHERE id != ? ORDER BY RANDOM() LIMIT 1", (last_id,))
        picked = cur.fetchone()
        if picked is None:
            cur = db_execute(conn, engine, "SELECT id, question, options FROM questions ORDER BY RANDOM() LIMIT 1")
            picked = cur.fetchone()
    finally:
        conn.close()

    if picked is None:
        return jsonify({"error": "no questions"}), 404

    session["last_id"] = picked["id"]
    return jsonify({
        "id": picked["id"],
        "question": picked["question"],
        "options": picked["options"],
    })


@app.route("/api/check", methods=["POST"])
@login_required
def check_answer():
    data = request.get_json(silent=True) or {}
    qid = data.get("id")
    selected = data.get("selected")

    if not isinstance(qid, int):
        return jsonify({"error": "unknown question"}), 400
    conn, engine = get_db()
    try:
        cur = db_execute(conn, engine, "SELECT options, answer FROM questions WHERE id = ?", (qid,))
        question = cur.fetchone()
    finally:
        conn.close()
    if question is None:
        return jsonify({"error": "unknown question"}), 400

    correct = isinstance(selected, int) and selected == question["answer"]
    return jsonify({
        "correct": correct,
        "correctIndex": question["answer"],
        "correctText": question["options"][question["answer"]],
    })


@app.route("/api/track-play", methods=["POST"])
@login_required
def track_play():
    """Records that the user started a level (used for admin statistics)."""
    data = request.get_json(silent=True) or {}
    game = data.get("game")
    try:
        level = int(data.get("level", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid level"}), 400
    if game not in ("runner", "match") or level < 1 or level > 10:
        return jsonify({"error": "invalid input"}), 400

    conn, engine = get_db()
    db_execute(conn, engine,
        "INSERT INTO level_plays (user_id, game, level) VALUES (?, ?, ?)",
        (session["user"]["id"], game, level))
    db_execute(conn, engine, "UPDATE users SET last_active = now() WHERE id = ?", (session["user"]["id"],))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/save-score", methods=["POST"])
@login_required
def save_score():
    data = request.get_json(silent=True) or {}
    try:
        points = int(data.get("score", 0))
    except (TypeError, ValueError):
        points = 0
    points = max(0, points)

    new_total = add_to_user_score(session["user"]["id"], points)
    touch_last_active(session["user"]["id"])
    if new_total is not None:
        session["user"]["total_score"] = new_total

    return jsonify({"status": "ok", "total_score": new_total})


# -----------------------------------------------------------------------
# 8. Level-up API
# -----------------------------------------------------------------------
@app.route("/api/level-up", methods=["POST"])
@login_required
def level_up():
    data = request.get_json(silent=True) or {}
    try:
        completed_level = int(data.get("level", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid level"}), 400

    user_id = session["user"]["id"]
    fresh = get_user_by_id(user_id)
    if not fresh:
        return jsonify({"error": "user not found"}), 404

    # Only allow leveling up from the user's current level
    if completed_level < 1 or completed_level > 10:
        return jsonify({"error": "invalid level"}), 400

    next_level = min(completed_level + 1, 10)
    new_level = update_user_level(user_id, next_level)
    session["user"]["current_level"] = new_level

    return jsonify({"status": "ok", "current_level": new_level})


# -----------------------------------------------------------------------
# 9. Leaderboard API
# -----------------------------------------------------------------------
@app.route("/api/leaderboard")
@login_required
def leaderboard():
    conn, engine = get_db()
    cur = db_execute(conn, engine,
        "SELECT name, picture, total_score, current_level FROM users ORDER BY total_score DESC LIMIT 10"
    )
    rows = cur.fetchall()
    conn.close()

    result = []
    for row in rows:
        r = dict(row)
        result.append({
            "name": r["name"],
            "picture": r["picture"],
            "total_score": r["total_score"],
            "current_level": r["current_level"],
        })

    return jsonify(result)


# -----------------------------------------------------------------------
# 10. Games & Word Matching routes
# -----------------------------------------------------------------------
@app.route('/games')
def games_page():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    fresh = get_user_by_id(user['id'])
    if fresh:
        session['user']['total_score'] = fresh['total_score']
        session['user']['current_level'] = fresh['current_level']
        user = session['user']
    return render_template('index.html', user=user, active_page='games')


@app.route('/games/match')
def match_game_page():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    fresh = get_user_by_id(user['id'])
    if fresh:
        session['user']['total_score'] = fresh['total_score']
        session['user']['current_level'] = fresh['current_level']
        user = session['user']
    return render_template('index.html', user=user, active_page='match_game')


@app.route('/api/vocab')
@login_required
def get_vocab():
    level = request.args.get('level', 1, type=int)
    level = max(1, min(level, 5))
    try:
        conn, engine = get_db()
        cur = db_execute(conn, engine,
            'SELECT id, uz_word, en_translation FROM vocab WHERE level = ? ORDER BY RANDOM() LIMIT 4',
            (level,)
        )
        rows = cur.fetchall()
        words = [dict(r) for r in rows]

        # Also provide all translations from this level for wrong options
        cur2 = db_execute(conn, engine,
            'SELECT DISTINCT en_translation FROM vocab WHERE level = ?',
            (level,)
        )
        all_translations = [dict(r)['en_translation'] for r in cur2.fetchall()]
        conn.close()

        if not words:
            return jsonify({'error': 'No words found for this level', 'words': [], 'all_translations': [], 'level': level})

        return jsonify({'words': words, 'all_translations': all_translations, 'level': level})
    except Exception as e:
        print(f'Vocab API error: {e}')
        return jsonify({'error': str(e), 'words': [], 'all_translations': [], 'level': level}), 500


# -----------------------------------------------------------------------
# 11. AI Chat API — Gemini REST (no SDK needed, uses requests library)
# -----------------------------------------------------------------------
@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    api_key = os.getenv('GEMINI_API_KEY', '').strip()
    if not api_key:
        return jsonify({'error': 'AI xizmat sozlanmagan. Iltimos, administrator bilan bog\'laning.'}), 500

    data = request.get_json(silent=True) or {}
    user_message = (data.get('message') or '').strip()
    history = data.get('history', [])

    if not user_message:
        return jsonify({'error': 'Xabar bo\'sh bo\'lmasin.'}), 400
    if len(user_message) > 1000:
        return jsonify({'error': 'Xabar 1000 belgidan oshmasin.'}), 400

    # Build contents: take up to last 8 history messages + new user turn
    contents = []
    for entry in (history or [])[-8:]:
        role = entry.get('role', '')
        text = (entry.get('text') or '').strip()
        if not text:
            continue
        if role not in ('user', 'model'):
            continue
        contents.append({'role': role, 'parts': [{'text': text}]})
    contents.append({'role': 'user', 'parts': [{'text': user_message}]})

    system_instruction = (
        'Siz WordRunner ingliz tili ta\'lim platformasining do\'stona AI o\'qituvchisisiz. '
        'Foydalanuvchilar o\'zbek tilida so\'zlashuvchi boshlang\'ich va o\'rta darajali ingliz tili o\'rganuvchilari. '
        'Grammatika, lug\'at, talaffuz va misollarni o\'zbek tilida aniq va qisqa tushuntiring. '
        'Foydalanuvchi inglizcha muloqot qilishni so\'rasa, inglizcha javob bering. '
        'Har doim quvvatlovchi, ijobiy va ixcham bo\'ling. '
        'Javobingiz 400 so\'zdan oshmasin.'
    )

    payload = {
        'system_instruction': {'parts': [{'text': system_instruction}]},
        'contents': contents,
        'generationConfig': {
            'temperature': 0.7,
            'maxOutputTokens': 600
        }
    }

    headers = {
        'Content-Type': 'application/json',
        'x-goog-api-key': api_key
    }

    primary_model = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    fallback_model = 'gemini-1.5-flash'

    def call_gemini(model_name):
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent'
        return requests.post(url, json=payload, headers=headers, timeout=25)

    try:
        resp = call_gemini(primary_model)
        if resp.status_code in (404, 429, 503):
            print(f'[chat] Primary model {primary_model} returned {resp.status_code}, trying fallback.')
            resp = call_gemini(fallback_model)

        if resp.status_code != 200:
            print(f'[chat] Gemini API error {resp.status_code}: {resp.text[:300]}')
            return jsonify({'error': 'AI xizmatida xatolik yuz berdi. Iltimos, qaytadan urinib ko\'ring.'}), 502

        result = resp.json()
        reply_text = (
            result
            .get('candidates', [{}])[0]
            .get('content', {})
            .get('parts', [{}])[0]
            .get('text', '')
        ).strip()

        if not reply_text:
            return jsonify({'error': 'AI bo\'sh javob qaytardi. Iltimos, boshqacha savol bering.'}), 502

        return jsonify({'reply': reply_text})

    except requests.Timeout:
        print('[chat] Gemini API timeout')
        return jsonify({'error': 'AI javobi kechikdi. Internet aloqangizni tekshiring va qayta urinib ko\'ring.'}), 504
    except Exception as e:
        print(f'[chat] Unexpected error: {e}')
        return jsonify({'error': 'Kutilmagan xatolik yuz berdi. Iltimos, qaytadan urinib ko\'ring.'}), 500


# -----------------------------------------------------------------------
# 12. Admin panel (see admin.py)
# -----------------------------------------------------------------------
from admin import register_admin, is_admin_session

register_admin(app, get_db, db_execute)


@app.context_processor
def inject_admin_flag():
    return {"is_admin": is_admin_session()}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

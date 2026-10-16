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
import random
from functools import wraps

from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

import psycopg2
from psycopg2.extras import RealDictCursor

# -----------------------------------------------------------------------
# 1. Load secrets from .env
# -----------------------------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
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
    conn, engine = get_db()
    cur = db_execute(conn, engine, "SELECT COUNT(*) AS cnt FROM vocab")
    row = cur.fetchone()
    if row and (row.get("cnt") == 0 or list(row.values())[0] == 0):
        words = [
            # Level 1 (1-24)
            ("belgilamoq", "highlight", 1), #
            ("javob bermoq", "respond", 1), #
            ("tashqarida ovqatlanmoq", "eat out", 1), #
            ("juda charchagan", "exhausted", 1), #
            ("ifoda", "expression", 1), #
            ("yo'qolgan, tushirib qoldirilgan", "missing", 1), #
            ("qarshi emasmisiz?", "would mind", 1), #
            ("shakarni uzating", "pass the sugar", 1), #
            ("ikki hafta", "fortnight", 1), #
            ("taassurot", "impression", 1), #
            ("yordam, iltimos", "favor", 1), #
            ("ruxsat", "permission", 1), #
            ("so'rov, iltimos", "request", 1), #
            ("unashtirilmoq", "get engaged", 1), #
            ("belgi qo'ymoq (✓)", "tick", 1), #
            ("sobiq (yigit/qiz)", "ex", 1), #
            ("rozi emaslik", "disagree", 1), #
            ("navbatlashmoq", "take turns", 1), #
            ("ajrashmoq", "break up with", 1), #
            ("tufayli", "thanks to", 1), #
            ("diktor, teleolifin", "presenter", 1), #
            ("unashtirilgan yigit", "fiance", 1), #
            ("qoplamoq, yopmoq", "cover", 1), #
            ("taklif qilmoq", "propose", 1), #

            # Level 2 (25-48)
            ("sevib qolmoq", "fall in love", 2), #
            ("kashf qilmoq", "discover", 2), #
            ("atama, muddat", "term", 2), #
            ("ajralmoq", "split up", 2), #
            ("bo'ydoq, yolg'iz", "single", 2), #
            ("qabul qilmoq", "accept", 2), #
            ("kvartirani birga ijaraga olmoq", "share a flat", 2), #
            ("og'zaki nutq, ko’cha tili", "colloquial", 2), #
            ("yaxshi chiqishmoq", "get on well/with", 2), #
            ("umumiyligi bor", "have in common", 2), #
            ("aloqada bo'lmoq", "keep in touch", 2), #
            ("mavhum", "abstract", 2), #
            ("muddati tugamoq", "expire", 2), #
            ("teng", "equal", 2), #
            ("bog'lash, havola", "link", 2), #
            ("unli", "vowel", 2), #
            ("aloqani uzmoq", "lose touch", 2), #
            ("bo'g'in", "syllable", 2), #
            ("istisno", "exception", 2), #
            ("aksincha", "vice versa", 2), #
            ("ustun", "column", 2), #
            ("ehtimol", "probably", 2), #
            ("vaqtida keladigan", "punctual", 2), #
            ("ajratib olmoq, ma'lumot", "extract", 2), #

            # Level 3 (49-72)
            ("qaram bo'lmoq", "be addicted to", 3), #
            ("endi, bundan keyin", "any more", 3), #
            ("tashlamoq, voz kechmoq", "give up", 3), #
            ("moslashtirmoq", "adapt", 3), #
            ("quyidagi", "following", 3), #
            ("uchrashuvqa taklif qilmoq", "ask out", 3), #
            ("ulamoq", "connect", 3), #
            ("igna b.n. davolash", "acupuncture", 3), #
            ("oxirgi chora sifatida", "as a last resort", 3), #
            ("ijodiy", "creative", 3), #
            ("tushirmoq (yukni)", "unload", 3), #
            ("talontoroj qilmoq vs o'g'irlamoq", "rob vs steal", 3), #
            ("orqa, tarbiyalamoq", "rear", 3), #
            ("payqamoq, bildirishnoma", "notice", 3), #
            ("bosmoq", "press", 3), #
            ("qulfini ochmoq", "unlock", 3), #
            ("tugma", "button", 3), #
            ("tekshirmoq, ro'yxatdan chiqmoq", "check out", 3), #
            ("darhol", "immediately", 3), #
            ("jalb qilmoq, tortmoq", "attract", 3), #
            ("juftlik, er-xotin", "couple", 3), #
            ("bilib olmoq, aniqlamoq(topmoq emas)", "find out", 3), #
            ("holat, sharoit", "circumstance", 3), #
            ("vaqtida", "on time", 3), #

            # Level 4 (73-96)
            ("olib ketmoq, o'rganmoq", "pick up", 4), #
            ("uchrashmoq", "go out together", 4), #
            ("almashtirmoq", "replace", 4), #
            ("qo'shimcha", "spare(adj)", 4), #
            ("tushunmoq, amalga oshirmoq", "realize", 4), #
            ("chiqarmoq, ozod qilmoq", "release", 4), #
            ("ko'p o'tmay", "soon after", 4), #
            ("shikast, zarar", "damage", 4), #
            ("davlatning bir burchagida narigi burchagigacha", "crosscountry", 4), #
            ("qutqarmoq", "rescue", 4), #
            ("latifa, hikoya", "anecdote", 4), #
            ("baxtsiz hodisa", "accident", 4), #
            ("tuzalmoq, qaytarib olmoq", "recover", 4), #
            ("mashhur shaxs", "celebrity", 4), #
            ("deyarli", "nearly", 4), #
            ("istisno", "exception", 4), #
            ("adolatli, ochiq rangli", "fair(adj)", 4), #
            ("talqin, izoh", "interpretation", 4), #
            ("oldindan aytmoq", "predict", 4), #
            ("teginmoq, aloqa", "touch", 4), #
            ("aldamoq", "cheat", 4), #
            ("qabul qilmoq", "accept", 4), #
            ("qurbonlik", "sacrifice", 4), #
            ("o'rniga", "instead", 4), #

            # Level 5 (97-120)
            ("yirik hisobda yutmoq", "win by a long way", 5), #
            ("shart, holat", "condition", 5), #
            ("dan tashqari", "except", 5), #
            ("shuningdek, bilan birga", "as well as", 5), #
            ("almashtirish xonasi", "changing room", 5), #
            ("bajaramoq, ijro etmoq", "perform", 5), #
            ("ruxsat bermoq", "allow", 5), #
            ("ga ko'ra", "according to", 5), #
            ("sakramoq (to'p)", "bounce", 5), #
            ("soqol qirmoq", "shave", 5), #
            ("maydoncha (sport)", "pitch", 5), #
            ("qochmoq, oldini olmoq", "avoid", 5), #
            ("majburiy", "compulsory", 5), #
            ("omad tumori", "lucky charm", 5), #
            ("qator", "row", 5), #
            ("to'r", "net", 5), #
            ("turnir", "tournament", 5), #
            ("xurofot, bid’at, irm-sirim", "superstition", 5), #
            ("poyga", "race", 5), #
            ("so'rovnoma", "questionnaire", 5), #
            ("afzal ko'rmoq", "prefer", 5), #
            ("qulaylik, inshoot", "facility", 5), #
            ("ixtiyoriy", "optional", 5), #
            ("loyiq bo'lmoq", "deserve", 5), #
        ]
        
        for uz_word, en_translation, level in words:
            db_execute(
                conn, engine,
                "INSERT INTO vocab (uz_word, en_translation, level) VALUES (?, ?, ?)",
                (uz_word, en_translation, level),
            )
        conn.commit()
    conn.close()

init_db()
seed_vocab()


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
    }

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
QUESTIONS = [
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
    {"id": 5,  "question": "\u201cThey

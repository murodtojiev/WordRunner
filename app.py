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


init_db()


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
    return render_template("index.html", user=user)


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
QUESTIONS_BY_ID = {q["id"]: q for q in QUESTIONS}


@app.route("/api/question")
@login_required
def get_question():
    last_id = session.get("last_id")
    choices = [q for q in QUESTIONS if q["id"] != last_id] or QUESTIONS
    picked = random.choice(choices)
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

    question = QUESTIONS_BY_ID.get(qid)
    if question is None:
        return jsonify({"error": "unknown question"}), 400

    correct = isinstance(selected, int) and selected == question["answer"]
    return jsonify({
        "correct": correct,
        "correctIndex": question["answer"],
        "correctText": question["options"][question["answer"]],
    })


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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

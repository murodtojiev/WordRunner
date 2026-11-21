"""
WordRunner — Admin panel backend
--------------------------------
Registered from app.py via register_admin(app, get_db, db_execute).

Security:
  - Only Google accounts listed in ADMIN_EMAILS (env, comma separated) get in.
    Default: murodtojievuz@gmail.com. The email must be verified by Google.
  - Non-admins get a plain 404 on /admin (the panel's existence is not revealed)
    and 403 on /admin/api/*.
  - Every non-GET API call must carry the header  X-Admin-Request: 1
    (together with SameSite=Lax cookies this blocks cross-site request forgery).
"""

import os
from contextlib import contextmanager
from functools import wraps

from flask import Blueprint, abort, jsonify, render_template, request, session
from psycopg2.extras import Json

CATEGORIES = ["synonym", "antonym", "vocabulary", "grammar", "plural", "spelling", "idiom"]
VOCAB_LEVELS = [1, 2, 3, 4, 5]
MAX_USER_LEVEL = 10
DEFAULT_ADMIN = "murodtojievuz@gmail.com"

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# -----------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------
def admin_emails():
    raw = os.getenv("ADMIN_EMAILS", DEFAULT_ADMIN)
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin_session():
    user = session.get("user")
    if not user:
        return False
    email = (user.get("email") or "").lower()
    return bool(user.get("email_verified")) and email in admin_emails()


def admin_page(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin_session():
            abort(404)
        return view(*args, **kwargs)
    return wrapped


def admin_api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin_session():
            return jsonify({"error": "Ruxsat yo'q"}), 403
        if request.method != "GET" and request.headers.get("X-Admin-Request") != "1":
            return jsonify({"error": "Noto'g'ri so'rov"}), 400
        return view(*args, **kwargs)
    return wrapped


# -----------------------------------------------------------------------
# Registration (receives DB helpers from app.py to avoid circular imports)
# -----------------------------------------------------------------------
def register_admin(app, get_db, db_execute):

    @contextmanager
    def db():
        conn, engine = get_db()
        try:
            yield lambda sql, params=(): db_execute(conn, engine, sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def iso(dt):
        return dt.isoformat() if dt else None

    def page_args(default_per_page=20):
        page = max(1, request.args.get("page", 1, type=int))
        per_page = default_per_page
        return page, per_page, (page - 1) * per_page

    def like(term):
        return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    # ------------------------------------------------------------------
    # Page
    # ------------------------------------------------------------------
    @admin_bp.route("/", strict_slashes=False)
    @admin_page
    def admin_index():
        return render_template(
            "admin.html",
            admin=session["user"],
            categories=CATEGORIES,
        )

    # ------------------------------------------------------------------
    # 1. Dashboard
    # ------------------------------------------------------------------
    @admin_bp.route("/api/stats")
    @admin_api
    def stats():
        with db() as q:
            row = q("""
                SELECT COUNT(*) AS total,
                       COALESCE(AVG(total_score), 0) AS avg_score,
                       COUNT(*) FILTER (
                           WHERE last_active >= (date_trunc('day', now() AT TIME ZONE 'Asia/Tashkent')
                                                 AT TIME ZONE 'Asia/Tashkent')
                       ) AS active_today,
                       COUNT(*) FILTER (WHERE last_active >= now() - interval '7 days') AS active_week
                FROM users
            """).fetchone()

            plays = q("""
                SELECT game, level, COUNT(*) AS plays
                FROM level_plays GROUP BY game, level ORDER BY plays DESC, level ASC
            """).fetchall()

            users_by_level = q(
                "SELECT current_level AS level, COUNT(*) AS cnt FROM users GROUP BY current_level ORDER BY current_level"
            ).fetchall()

            top = q(
                "SELECT name, picture, total_score, current_level FROM users ORDER BY total_score DESC LIMIT 5"
            ).fetchall()

            n_questions = q("SELECT COUNT(*) AS c FROM questions").fetchone()["c"]
            n_vocab = q("SELECT COUNT(*) AS c FROM vocab").fetchone()["c"]

        plays_by_level = {"runner": {}, "match": {}}
        for p in plays:
            plays_by_level[p["game"]][str(p["level"])] = p["plays"]

        most_played = {"runner": None, "match": None, "overall": None}
        for p in plays:  # already sorted by plays DESC
            if most_played["overall"] is None:
                most_played["overall"] = {"game": p["game"], "level": p["level"], "plays": p["plays"]}
            if most_played[p["game"]] is None:
                most_played[p["game"]] = {"level": p["level"], "plays": p["plays"]}

        return jsonify({
            "total_users": row["total"],
            "active_today": row["active_today"],
            "active_week": row["active_week"],
            "avg_score": round(float(row["avg_score"]), 1),
            "most_played": most_played,
            "plays_by_level": plays_by_level,
            "users_by_level": [{"level": r["level"], "count": r["cnt"]} for r in users_by_level],
            "top_players": [dict(r) for r in top],
            "total_questions": n_questions,
            "total_vocab": n_vocab,
        })

    # ------------------------------------------------------------------
    # 2. Users
    # ------------------------------------------------------------------
    USER_SORTS = {
        "score": "total_score DESC, id ASC",
        "level": "current_level DESC, total_score DESC",
        "name": "LOWER(name) ASC",
        "recent": "last_active DESC NULLS LAST, id ASC",
    }

    @admin_bp.route("/api/users")
    @admin_api
    def list_users():
        page, per_page, offset = page_args(20)
        term = (request.args.get("q") or "").strip()
        order = USER_SORTS.get(request.args.get("sort"), USER_SORTS["score"])

        where, params = "", []
        if term:
            where = "WHERE name ILIKE ? OR email ILIKE ?"
            params = [like(term), like(term)]

        with db() as q:
            total = q(f"SELECT COUNT(*) AS c FROM users {where}", params).fetchone()["c"]
            rows = q(
                f"""SELECT id, name, email, picture, total_score, current_level, last_active
                    FROM users {where} ORDER BY {order} LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()
            blocked = q("SELECT email, blocked_at FROM blocked_emails ORDER BY blocked_at DESC").fetchall()

        users = []
        for r in rows:
            u = dict(r)
            u["last_active"] = iso(u["last_active"])
            u["is_admin"] = (u["email"] or "").lower() in admin_emails()
            users.append(u)

        return jsonify({
            "users": users,
            "total": total,
            "page": page,
            "pages": max(1, -(-total // per_page)),
            "blocked": [{"email": b["email"], "blocked_at": iso(b["blocked_at"])} for b in blocked],
            "max_level": MAX_USER_LEVEL,
        })

    @admin_bp.route("/api/users/<int:user_id>", methods=["PATCH"])
    @admin_api
    def update_user(user_id):
        data = request.get_json(silent=True) or {}
        action = data.get("action")

        with db() as q:
            if q("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                return jsonify({"error": "O'yinchi topilmadi"}), 404

            if action == "reset_score":
                q("UPDATE users SET total_score = 0 WHERE id = ?", (user_id,))
            elif action == "set_level":
                try:
                    level = int(data.get("level"))
                except (TypeError, ValueError):
                    return jsonify({"error": "Bosqich noto'g'ri"}), 400
                if not 1 <= level <= MAX_USER_LEVEL:
                    return jsonify({"error": f"Bosqich 1 dan {MAX_USER_LEVEL} gacha bo'lishi kerak"}), 400
                q("UPDATE users SET current_level = ? WHERE id = ?", (level, user_id))
            else:
                return jsonify({"error": "Noma'lum amal"}), 400

            row = q("SELECT id, total_score, current_level FROM users WHERE id = ?", (user_id,)).fetchone()
        return jsonify({"status": "ok", "user": dict(row)})

    @admin_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
    @admin_api
    def delete_user(user_id):
        if user_id == session["user"]["id"]:
            return jsonify({"error": "O'zingizni o'chira olmaysiz"}), 400
        block = request.args.get("block") == "1"

        with db() as q:
            row = q("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                return jsonify({"error": "O'yinchi topilmadi"}), 404
            email = (row["email"] or "").lower()
            if email in admin_emails():
                return jsonify({"error": "Adminni o'chirib bo'lmaydi"}), 400
            if block and email:
                q("INSERT INTO blocked_emails (email) VALUES (?) ON CONFLICT DO NOTHING", (email,))
            q("DELETE FROM level_plays WHERE user_id = ?", (user_id,))
            q("DELETE FROM users WHERE id = ?", (user_id,))
        return jsonify({"status": "ok", "blocked": bool(block and email)})

    @admin_bp.route("/api/blocked/<path:email>", methods=["DELETE"])
    @admin_api
    def unblock(email):
        with db() as q:
            q("DELETE FROM blocked_emails WHERE email = ?", (email.lower(),))
        return jsonify({"status": "ok"})

    # ------------------------------------------------------------------
    # 3. English Runner questions
    # ------------------------------------------------------------------
    def clean_question(data):
        """Returns (cleaned_dict, error_message)."""
        text = (data.get("question") or "").strip()
        options = data.get("options")
        category = data.get("category")
        answer = data.get("answer")
        difficulty = data.get("difficulty", 2)

        if not text:
            return None, "Savol matni bo'sh bo'lmasligi kerak"
        if len(text) > 300:
            return None, "Savol matni 300 belgidan oshmasin"
        if not isinstance(options, list) or len(options) != 4:
            return None, "Aynan 4 ta variant kerak"
        options = [str(o).strip() for o in options]
        if any(not o for o in options):
            return None, "Barcha variantlar to'ldirilishi kerak"
        if len({o.lower() for o in options}) != 4:
            return None, "Variantlar bir-biridan farq qilishi kerak"
        if any(len(o) > 100 for o in options):
            return None, "Variant 100 belgidan oshmasin"
        if not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer <= 3:
            return None, "To'g'ri javob tanlanmagan"
        if category not in CATEGORIES:
            return None, "Kategoriya noto'g'ri"
        if not isinstance(difficulty, int) or isinstance(difficulty, bool) or difficulty not in (1, 2, 3, 4):
            return None, "Daraja noto'g'ri"
        return {"question": text, "options": options, "answer": answer, "category": category,
                "difficulty": difficulty}, None

    @admin_bp.route("/api/questions")
    @admin_api
    def list_questions():
        page, per_page, offset = page_args(20)
        term = (request.args.get("q") or "").strip()
        category = request.args.get("category")

        conds, params = [], []
        if term:
            conds.append("question ILIKE ?")
            params.append(like(term))
        if category in CATEGORIES:
            conds.append("category = ?")
            params.append(category)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        with db() as q:
            total = q(f"SELECT COUNT(*) AS c FROM questions {where}", params).fetchone()["c"]
            rows = q(
                f"SELECT id, question, options, answer, category, difficulty FROM questions {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()
            counts = q("SELECT category, COUNT(*) AS c FROM questions GROUP BY category").fetchall()
            all_total = q("SELECT COUNT(*) AS c FROM questions").fetchone()["c"]

        return jsonify({
            "questions": [dict(r) for r in rows],
            "total": total,
            "all_total": all_total,
            "page": page,
            "pages": max(1, -(-total // per_page)),
            "category_counts": {c["category"]: c["c"] for c in counts},
        })

    @admin_bp.route("/api/questions", methods=["POST"])
    @admin_api
    def create_question():
        item, err = clean_question(request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), 400
        with db() as q:
            row = q(
                "INSERT INTO questions (question, options, answer, category, difficulty) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (item["question"], Json(item["options"]), item["answer"], item["category"], item["difficulty"]),
            ).fetchone()
        return jsonify({"status": "ok", "id": row["id"]}), 201

    @admin_bp.route("/api/questions/<int:qid>", methods=["PUT"])
    @admin_api
    def update_question(qid):
        item, err = clean_question(request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), 400
        with db() as q:
            cur = q(
                "UPDATE questions SET question = ?, options = ?, answer = ?, category = ?, difficulty = ? WHERE id = ?",
                (item["question"], Json(item["options"]), item["answer"], item["category"], item["difficulty"], qid),
            )
            if cur.rowcount == 0:
                return jsonify({"error": "Savol topilmadi"}), 404
        return jsonify({"status": "ok"})

    @admin_bp.route("/api/questions/<int:qid>", methods=["DELETE"])
    @admin_api
    def delete_question(qid):
        with db() as q:
            if q("SELECT COUNT(*) AS c FROM questions").fetchone()["c"] <= 4:
                return jsonify({"error": "Kamida 4 ta savol qolishi kerak (o'yin ishlashi uchun)"}), 400
            cur = q("DELETE FROM questions WHERE id = ?", (qid,))
            if cur.rowcount == 0:
                return jsonify({"error": "Savol topilmadi"}), 404
        return jsonify({"status": "ok"})

    # ------------------------------------------------------------------
    # 4. Word-match vocabulary
    # ------------------------------------------------------------------
    def clean_vocab(data):
        uz = (data.get("uz_word") or "").strip()
        en = (data.get("en_translation") or "").strip()
        try:
            level = int(data.get("level"))
        except (TypeError, ValueError):
            return None, "Bosqich noto'g'ri"
        if not uz or not en:
            return None, "O'zbekcha va inglizcha so'z to'ldirilishi kerak"
        if len(uz) > 150 or len(en) > 150:
            return None, "So'z 150 belgidan oshmasin"
        if level not in VOCAB_LEVELS:
            return None, "Bosqich 1 dan 5 gacha bo'lishi kerak"
        return {"uz_word": uz, "en_translation": en, "level": level}, None

    @admin_bp.route("/api/vocab")
    @admin_api
    def list_vocab():
        page, per_page, offset = page_args(25)
        term = (request.args.get("q") or "").strip()
        level = request.args.get("level", type=int)

        conds, params = [], []
        if term:
            conds.append("(uz_word ILIKE ? OR en_translation ILIKE ?)")
            params += [like(term), like(term)]
        if level in VOCAB_LEVELS:
            conds.append("level = ?")
            params.append(level)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        with db() as q:
            total = q(f"SELECT COUNT(*) AS c FROM vocab {where}", params).fetchone()["c"]
            rows = q(
                f"SELECT id, uz_word, en_translation, level FROM vocab {where} ORDER BY level, id DESC LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()
            counts = q("SELECT level, COUNT(*) AS c FROM vocab GROUP BY level").fetchall()
            all_total = q("SELECT COUNT(*) AS c FROM vocab").fetchone()["c"]

        return jsonify({
            "words": [dict(r) for r in rows],
            "total": total,
            "all_total": all_total,
            "page": page,
            "pages": max(1, -(-total // per_page)),
            "level_counts": {str(c["level"]): c["c"] for c in counts},
        })

    @admin_bp.route("/api/vocab", methods=["POST"])
    @admin_api
    def create_vocab():
        item, err = clean_vocab(request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), 400
        with db() as q:
            row = q(
                "INSERT INTO vocab (uz_word, en_translation, level) VALUES (?, ?, ?) RETURNING id",
                (item["uz_word"], item["en_translation"], item["level"]),
            ).fetchone()
        return jsonify({"status": "ok", "id": row["id"]}), 201

    @admin_bp.route("/api/vocab/<int:vid>", methods=["PUT"])
    @admin_api
    def update_vocab(vid):
        item, err = clean_vocab(request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), 400
        with db() as q:
            cur = q(
                "UPDATE vocab SET uz_word = ?, en_translation = ?, level = ? WHERE id = ?",
                (item["uz_word"], item["en_translation"], item["level"], vid),
            )
            if cur.rowcount == 0:
                return jsonify({"error": "So'z topilmadi"}), 404
        return jsonify({"status": "ok"})

    @admin_bp.route("/api/vocab/<int:vid>", methods=["DELETE"])
    @admin_api
    def delete_vocab(vid):
        with db() as q:
            cur = q("DELETE FROM vocab WHERE id = ?", (vid,))
            if cur.rowcount == 0:
                return jsonify({"error": "So'z topilmadi"}), 404
        return jsonify({"status": "ok"})

    # ------------------------------------------------------------------
    # JSON error responses inside the admin API
    # ------------------------------------------------------------------
    @admin_bp.errorhandler(Exception)
    def admin_error(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return err
        app.logger.exception("Admin API error")
        if request.path.startswith("/admin/api/"):
            return jsonify({"error": "Server xatosi"}), 500
        raise err

    app.register_blueprint(admin_bp)

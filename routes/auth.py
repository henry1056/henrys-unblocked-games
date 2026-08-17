import re
import bcrypt
from flask import Blueprint, request, jsonify, session
from db import db, get_user_by_username
from auth import current_user, timeout_remaining_minutes, require_auth

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify(error="Username and password are required."), 400
    if not USERNAME_RE.match(username):
        return jsonify(error="Username must be 3–20 characters: letters, numbers, underscores."), 400
    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters."), 400

    if get_user_by_username(username):
        return jsonify(error="That username is already taken."), 409

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?,?)",
            (username, hashed)
        )
        session["user_id"] = cur.lastrowid

    return jsonify(ok=True, username=username, role="user")


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify(error="Username and password are required."), 400

    user = get_user_by_username(username)
    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return jsonify(error="Invalid username or password."), 401
    if user["banned"]:
        return jsonify(error="This account has been banned."), 403

    session["user_id"] = user["id"]
    mins = timeout_remaining_minutes(dict(user))
    return jsonify(ok=True, username=user["username"], role=user["role"], timedOutMinutes=mins)


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/me")
@require_auth
def me():
    user = current_user()
    mins = timeout_remaining_minutes(user)
    return jsonify(
        id=user["id"],
        username=user["username"],
        role=user["role"],
        timedOutMinutes=mins,
    )


@bp.post("/change-password")
@require_auth
def change_password():
    user = current_user()
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not current_password or not new_password:
        return jsonify(error="Current and new password are required."), 400
    if not bcrypt.checkpw(current_password.encode(), user["password_hash"].encode()):
        return jsonify(error="Current password is incorrect."), 401
    if len(new_password) < 8:
        return jsonify(error="New password must be at least 8 characters."), 400
    if new_password == current_password:
        return jsonify(error="New password must be different from the current one."), 400

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    with db() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user["id"]))

    return jsonify(ok=True)

import time
from flask import Blueprint, request, jsonify
from db import db, log_action
from auth import current_user, require_role

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _get_target(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


@bp.get("/users")
@require_role("admin")
def list_users():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, username, role, banned, ban_reason, timeout_until, timeout_reason, created_at "
            "FROM users ORDER BY created_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/users/<int:uid>/ban")
@require_role("admin")
def ban_user(uid):
    admin = current_user()
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "")[:300]
    with db() as conn:
        target = _get_target(conn, uid)
        if not target:
            return jsonify(error="User not found."), 404
        if target["role"] == "admin":
            return jsonify(error="Cannot ban another admin."), 400
        conn.execute("UPDATE users SET banned=1, ban_reason=? WHERE id=?", (reason, uid))
    log_action(admin["username"], target["username"], "ban", reason)
    return jsonify(ok=True)


@bp.post("/users/<int:uid>/unban")
@require_role("admin")
def unban_user(uid):
    admin = current_user()
    with db() as conn:
        target = _get_target(conn, uid)
        if not target:
            return jsonify(error="User not found."), 404
        conn.execute("UPDATE users SET banned=0, ban_reason=NULL WHERE id=?", (uid,))
    log_action(admin["username"], target["username"], "unban")
    return jsonify(ok=True)


@bp.post("/users/<int:uid>/timeout")
@require_role("admin")
def timeout_user(uid):
    admin = current_user()
    data = request.get_json(silent=True) or {}
    try:
        minutes = int(data.get("minutes", 0))
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0 or minutes > 60 * 24 * 30:
        return jsonify(error="Provide a valid number of minutes (max 43200)."), 400
    reason = (data.get("reason") or "")[:300]
    until = int(time.time() * 1000) + minutes * 60000

    with db() as conn:
        target = _get_target(conn, uid)
        if not target:
            return jsonify(error="User not found."), 404
        if target["role"] == "admin":
            return jsonify(error="Cannot time out another admin."), 400
        conn.execute(
            "UPDATE users SET timeout_until=?, timeout_reason=? WHERE id=?",
            (until, reason, uid)
        )
    log_action(admin["username"], target["username"], f"timeout ({minutes}m)", reason)
    return jsonify(ok=True, until=until)


@bp.post("/users/<int:uid>/clear-timeout")
@require_role("admin")
def clear_timeout(uid):
    admin = current_user()
    with db() as conn:
        target = _get_target(conn, uid)
        if not target:
            return jsonify(error="User not found."), 404
        conn.execute("UPDATE users SET timeout_until=NULL, timeout_reason=NULL WHERE id=?", (uid,))
    log_action(admin["username"], target["username"], "clear-timeout")
    return jsonify(ok=True)


@bp.post("/users/<int:uid>/role")
@require_role("admin")
def set_role(uid):
    admin = current_user()
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    if role not in ("user", "trusted", "admin"):
        return jsonify(error="Role must be user, trusted, or admin."), 400
    with db() as conn:
        target = _get_target(conn, uid)
        if not target:
            return jsonify(error="User not found."), 404
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
    log_action(admin["username"], target["username"], f"role → {role}")
    return jsonify(ok=True)


@bp.get("/log")
@require_role("admin")
def mod_log():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM mod_log ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/users/<int:uid>/set-password")
@require_role("admin")
def set_password(uid):
    import bcrypt
    admin = current_user()
    data = request.get_json(silent=True) or {}
    new_password = data.get("new_password") or ""
    if len(new_password) < 8:
        return jsonify(error="Password must be at least 8 characters."), 400
    with db() as conn:
        target = _get_target(conn, uid)
        if not target:
            return jsonify(error="User not found."), 404
        new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, uid))
    log_action(admin["username"], target["username"], "password reset")
    return jsonify(ok=True)

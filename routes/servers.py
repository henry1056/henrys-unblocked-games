import secrets
from flask import Blueprint, request, jsonify
from db import db
from auth import require_auth, current_user

bp = Blueprint("servers", __name__, url_prefix="/api/servers")

def _is_owner_or_can_manage(conn, server_id, user_id):
    server = conn.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
    if not server: return False, None
    if server["owner_id"] == user_id: return True, server
    # Check roles
    member = conn.execute(
        "SELECT id FROM server_members WHERE server_id=? AND user_id=?",
        (server_id, user_id)
    ).fetchone()
    if not member: return False, server
    role = conn.execute("""
        SELECT sr.can_manage_roles FROM server_member_roles smr
        JOIN server_roles sr ON sr.id = smr.role_id
        WHERE smr.member_id=? AND sr.can_manage_roles=1
    """, (member["id"],)).fetchone()
    return bool(role), server

# ── Server CRUD ───────────────────────────────────────────────────────────────

@bp.get("/")
@require_auth
def list_servers():
    user = current_user()
    with db() as conn:
        rows = conn.execute("""
            SELECT s.id, s.name, s.description, s.icon, s.invite_code,
                   s.created_at, u.username AS owner,
                   (SELECT COUNT(*) FROM server_members WHERE server_id=s.id) AS member_count
            FROM servers s JOIN users u ON u.id=s.owner_id
            ORDER BY s.created_at DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@bp.post("/")
@require_auth
def create_server():
    user = current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:50]
    description = (data.get("description") or "").strip()[:200]
    if not name:
        return jsonify(error="Server name is required."), 400
    invite_code = secrets.token_urlsafe(8)
    with db() as conn:
        existing = conn.execute("SELECT id FROM servers WHERE name=?", (name,)).fetchone()
        if existing:
            return jsonify(error="A server with that name already exists."), 409
        cur = conn.execute(
            "INSERT INTO servers (name, description, owner_id, invite_code) VALUES (?,?,?,?)",
            (name, description, user["id"], invite_code)
        )
        server_id = cur.lastrowid
        # Auto-join owner as member
        mem = conn.execute(
            "INSERT INTO server_members (server_id, user_id) VALUES (?,?)",
            (server_id, user["id"])
        )
        # Create default roles
        conn.execute(
            "INSERT INTO server_roles (server_id, name, color, can_kick, can_manage_roles, position) VALUES (?,?,?,?,?,?)",
            (server_id, "Owner", "#ff3d81", 1, 1, 100)
        )
        mod_id = conn.execute(
            "INSERT INTO server_roles (server_id, name, color, can_kick, can_manage_roles, position) VALUES (?,?,?,?,?,?)",
            (server_id, "Mod", "#ffb84d", 1, 0, 50)
        ).lastrowid
        conn.execute(
            "INSERT INTO server_roles (server_id, name, color, can_kick, can_manage_roles, position) VALUES (?,?,?,?,?,?)",
            (server_id, "Member", "#39ff88", 0, 0, 1)
        )
        # Give owner the Owner role
        owner_role = conn.execute(
            "SELECT id FROM server_roles WHERE server_id=? AND name='Owner'", (server_id,)
        ).fetchone()
        conn.execute(
            "INSERT INTO server_member_roles (member_id, role_id) VALUES (?,?)",
            (mem.lastrowid, owner_role["id"])
        )
        # Default #general channel
        conn.execute(
            "INSERT INTO server_channels (server_id, name) VALUES (?,?)",
            (server_id, "general")
        )
    return jsonify(ok=True, id=server_id, invite_code=invite_code)

@bp.get("/<int:server_id>")
@require_auth
def get_server(server_id):
    with db() as conn:
        server = conn.execute("""
            SELECT s.*, u.username AS owner,
                   (SELECT COUNT(*) FROM server_members WHERE server_id=s.id) AS member_count
            FROM servers s JOIN users u ON u.id=s.owner_id WHERE s.id=?
        """, (server_id,)).fetchone()
        if not server:
            return jsonify(error="Server not found."), 404
        members = conn.execute("""
            SELECT sm.id AS member_id, u.id, u.username,
                   GROUP_CONCAT(sr.name, ',') AS roles,
                   GROUP_CONCAT(sr.color, ',') AS role_colors
            FROM server_members sm
            JOIN users u ON u.id=sm.user_id
            LEFT JOIN server_member_roles smr ON smr.member_id=sm.id
            LEFT JOIN server_roles sr ON sr.id=smr.role_id
            WHERE sm.server_id=?
            GROUP BY sm.id
        """, (server_id,)).fetchall()
        roles = conn.execute(
            "SELECT * FROM server_roles WHERE server_id=? ORDER BY position DESC",
            (server_id,)
        ).fetchall()
        channels = conn.execute(
            "SELECT * FROM server_channels WHERE server_id=? ORDER BY id",
            (server_id,)
        ).fetchall()
        history = conn.execute("""
            SELECT username, content, created_at FROM messages
            WHERE channel=? ORDER BY created_at DESC LIMIT 50
        """, (f"server:{server_id}:general",)).fetchall()
    return jsonify(
        server=dict(server),
        members=[dict(m) for m in members],
        roles=[dict(r) for r in roles],
        channels=[dict(c) for c in channels],
        history=[dict(h) for h in reversed(history)]
    )

@bp.post("/join")
@require_auth
def join_server():
    user = current_user()
    data = request.get_json(silent=True) or {}
    invite_code = (data.get("invite_code") or "").strip()
    with db() as conn:
        server = conn.execute("SELECT * FROM servers WHERE invite_code=?", (invite_code,)).fetchone()
        if not server:
            return jsonify(error="Invalid invite code."), 404
        existing = conn.execute(
            "SELECT id FROM server_members WHERE server_id=? AND user_id=?",
            (server["id"], user["id"])
        ).fetchone()
        if existing:
            return jsonify(error="You are already in this server."), 409
        mem = conn.execute(
            "INSERT INTO server_members (server_id, user_id) VALUES (?,?)",
            (server["id"], user["id"])
        )
        # Give Member role automatically
        member_role = conn.execute(
            "SELECT id FROM server_roles WHERE server_id=? AND name='Member'",
            (server["id"],)
        ).fetchone()
        if member_role:
            conn.execute(
                "INSERT INTO server_member_roles (member_id, role_id) VALUES (?,?)",
                (mem.lastrowid, member_role["id"])
            )
    return jsonify(ok=True, server_id=server["id"], server_name=server["name"])

@bp.delete("/<int:server_id>")
@require_auth
def delete_server(server_id):
    user = current_user()
    with db() as conn:
        server = conn.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
        if not server: return jsonify(error="Not found."), 404
        if server["owner_id"] != user["id"] and user["role"] != "admin":
            return jsonify(error="Only the owner can delete this server."), 403
        conn.execute("DELETE FROM server_member_roles WHERE member_id IN (SELECT id FROM server_members WHERE server_id=?)", (server_id,))
        conn.execute("DELETE FROM server_members WHERE server_id=?", (server_id,))
        conn.execute("DELETE FROM server_roles WHERE server_id=?", (server_id,))
        conn.execute("DELETE FROM server_channels WHERE server_id=?", (server_id,))
        conn.execute("DELETE FROM messages WHERE channel LIKE ?", (f"server:{server_id}:%",))
        conn.execute("DELETE FROM servers WHERE id=?", (server_id,))
    return jsonify(ok=True)

# ── Roles ─────────────────────────────────────────────────────────────────────

@bp.post("/<int:server_id>/roles")
@require_auth
def create_role(server_id):
    user = current_user()
    with db() as conn:
        can, server = _is_owner_or_can_manage(conn, server_id, user["id"])
        if not can: return jsonify(error="No permission."), 403
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()[:30]
        color = (data.get("color") or "#8590a6")[:7]
        can_kick = int(bool(data.get("can_kick")))
        can_manage = int(bool(data.get("can_manage_roles")))
        if not name: return jsonify(error="Role name required."), 400
        cur = conn.execute(
            "INSERT INTO server_roles (server_id, name, color, can_kick, can_manage_roles) VALUES (?,?,?,?,?)",
            (server_id, name, color, can_kick, can_manage)
        )
    return jsonify(ok=True, id=cur.lastrowid)

@bp.delete("/<int:server_id>/roles/<int:role_id>")
@require_auth
def delete_role(server_id, role_id):
    user = current_user()
    with db() as conn:
        can, _ = _is_owner_or_can_manage(conn, server_id, user["id"])
        if not can: return jsonify(error="No permission."), 403
        conn.execute("DELETE FROM server_member_roles WHERE role_id=?", (role_id,))
        conn.execute("DELETE FROM server_roles WHERE id=? AND server_id=?", (role_id, server_id))
    return jsonify(ok=True)

@bp.post("/<int:server_id>/members/<int:member_user_id>/roles/<int:role_id>")
@require_auth
def assign_role(server_id, member_user_id, role_id):
    user = current_user()
    with db() as conn:
        can, _ = _is_owner_or_can_manage(conn, server_id, user["id"])
        if not can: return jsonify(error="No permission."), 403
        member = conn.execute(
            "SELECT id FROM server_members WHERE server_id=? AND user_id=?",
            (server_id, member_user_id)
        ).fetchone()
        if not member: return jsonify(error="Member not found."), 404
        conn.execute(
            "INSERT OR IGNORE INTO server_member_roles (member_id, role_id) VALUES (?,?)",
            (member["id"], role_id)
        )
    return jsonify(ok=True)

@bp.delete("/<int:server_id>/members/<int:member_user_id>/roles/<int:role_id>")
@require_auth
def remove_role(server_id, member_user_id, role_id):
    user = current_user()
    with db() as conn:
        can, _ = _is_owner_or_can_manage(conn, server_id, user["id"])
        if not can: return jsonify(error="No permission."), 403
        member = conn.execute(
            "SELECT id FROM server_members WHERE server_id=? AND user_id=?",
            (server_id, member_user_id)
        ).fetchone()
        if not member: return jsonify(error="Member not found."), 404
        conn.execute(
            "DELETE FROM server_member_roles WHERE member_id=? AND role_id=?",
            (member["id"], role_id)
        )
    return jsonify(ok=True)

@bp.post("/<int:server_id>/kick/<int:member_user_id>")
@require_auth
def kick_member(server_id, member_user_id):
    user = current_user()
    if user["id"] == member_user_id:
        return jsonify(error="You can't kick yourself."), 400
    with db() as conn:
        can, server = _is_owner_or_can_manage(conn, server_id, user["id"])
        if not can:
            # check can_kick role
            member_self = conn.execute(
                "SELECT id FROM server_members WHERE server_id=? AND user_id=?",
                (server_id, user["id"])
            ).fetchone()
            kick_role = conn.execute("""
                SELECT sr.can_kick FROM server_member_roles smr
                JOIN server_roles sr ON sr.id=smr.role_id
                WHERE smr.member_id=? AND sr.can_kick=1
            """, (member_self["id"],)).fetchone() if member_self else None
            if not kick_role:
                return jsonify(error="No permission."), 403
        target_mem = conn.execute(
            "SELECT id FROM server_members WHERE server_id=? AND user_id=?",
            (server_id, member_user_id)
        ).fetchone()
        if not target_mem: return jsonify(error="Member not found."), 404
        conn.execute("DELETE FROM server_member_roles WHERE member_id=?", (target_mem["id"],))
        conn.execute("DELETE FROM server_members WHERE id=?", (target_mem["id"],))
    return jsonify(ok=True)

import os
import secrets
import zipfile
import shutil
from flask import Blueprint, request, jsonify
from db import db
from auth import current_user, require_auth, require_role, block_if_timed_out

bp = Blueprint("games", __name__, url_prefix="/api/games")

UPLOAD_DIR = os.environ.get(
    "UPLOAD_DIR",
    os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "games")
)
MAX_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB
ALLOWED_EXTENSIONS = {".html", ".htm", ".js", ".zip"}


def _allowed(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def _entry_type(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".html", ".htm"): return "html"
    if ext == ".js": return "js"
    if ext == ".zip": return "zip"
    return "html"


def _row_to_dict(row):
    return dict(row)


@bp.get("/")
def list_games():
    with db() as conn:
        rows = conn.execute("""
            SELECT games.id, games.title, games.description, games.filename,
                   games.file_type, games.icon, games.created_at,
                   users.username AS uploader
            FROM games JOIN users ON users.id = games.uploader_id
            WHERE games.approved = 1
            ORDER BY games.created_at DESC
        """).fetchall()
    return jsonify([_row_to_dict(r) for r in rows])


@bp.get("/pending")
@require_role("admin")
def list_pending():
    with db() as conn:
        rows = conn.execute("""
            SELECT games.id, games.title, games.description, games.filename,
                   games.file_type, games.icon, games.created_at,
                   users.username AS uploader
            FROM games JOIN users ON users.id = games.uploader_id
            WHERE games.approved = 0
            ORDER BY games.created_at DESC
        """).fetchall()
    return jsonify([_row_to_dict(r) for r in rows])


def _stream_save(file_stream, dest_path, max_bytes):
    """Stream-write a single file, enforcing max_bytes."""
    total = 0
    with open(dest_path, "wb") as out:
        while True:
            chunk = file_stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                os.remove(dest_path)
                raise ValueError("File too large. Maximum size is 5 GB.")
            out.write(chunk)
    return total


@bp.post("/")
@require_auth
@require_role("trusted", "admin")
@block_if_timed_out
def upload_game():
    """Single file upload: .html / .htm / .js / .zip"""
    user = current_user()
    if "gamefile" not in request.files:
        return jsonify(error="No file uploaded."), 400

    f = request.files["gamefile"]
    if not f.filename or not _allowed(f.filename):
        return jsonify(error="Only .html, .htm, .js, or .zip files are accepted."), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(f.filename)[1].lower()
    filename = f"{secrets.token_hex(8)}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    try:
        _stream_save(f.stream, filepath, MAX_SIZE)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    title = (request.form.get("title") or "Untitled Game").strip()[:80]
    description = (request.form.get("description") or "").strip()[:500]
    icon = (request.form.get("icon") or "").strip()[:500]
    file_type = _entry_type(filename)
    auto_approve = 1 if user["role"] == "admin" else 0

    with db() as conn:
        cur = conn.execute(
            "INSERT INTO games (title, description, filename, file_type, icon, uploader_id, approved) "
            "VALUES (?,?,?,?,?,?,?)",
            (title, description, filename, file_type, icon, user["id"], auto_approve)
        )
        game_id = cur.lastrowid

    return jsonify(ok=True, id=game_id, approved=bool(auto_approve), file_type=file_type)


@bp.post("/folder")
@require_auth
@require_role("trusted", "admin")
@block_if_timed_out
def upload_folder():
    """
    Multi-file folder upload. The browser sends every file inside the chosen
    folder as a separate field, preserving relative paths in the 'paths[]'
    field that the frontend sends alongside.

    We store everything in a unique subfolder under UPLOAD_DIR and serve it
    statically. The entry point is always index.html (or the first .html file).
    """
    user = current_user()
    files = request.files.getlist("files[]")
    paths = request.form.getlist("paths[]")

    if not files or not paths:
        return jsonify(error="No files received."), 400

    # Create unique folder
    folder_id = secrets.token_hex(8)
    folder_path = os.path.join(UPLOAD_DIR, folder_id)
    os.makedirs(folder_path, exist_ok=True)

    total_size = 0
    entry_point = None

    try:
        for f, rel_path in zip(files, paths):
            # Strip leading slashes / traversal attempts
            rel_path = rel_path.lstrip("/").replace("..", "")
            dest = os.path.join(folder_path, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            total_size += _stream_save(f.stream, dest, MAX_SIZE - total_size)

            # Pick entry point: prefer index.html at root, else first .html
            basename = os.path.basename(rel_path).lower()
            depth = rel_path.count("/")
            if basename == "index.html" and depth <= 1:
                entry_point = rel_path
            elif entry_point is None and basename.endswith(".html"):
                entry_point = rel_path

        if entry_point is None:
            # Fallback: look for any .html
            for root, dirs, fnames in os.walk(folder_path):
                for fn in fnames:
                    if fn.lower().endswith(".html"):
                        entry_point = os.path.relpath(os.path.join(root, fn), folder_path)
                        break
                if entry_point:
                    break

        if entry_point is None:
            shutil.rmtree(folder_path, ignore_errors=True)
            return jsonify(error="No .html entry point found in the uploaded folder."), 400

    except ValueError as e:
        shutil.rmtree(folder_path, ignore_errors=True)
        return jsonify(error=str(e)), 400
    except Exception as e:
        shutil.rmtree(folder_path, ignore_errors=True)
        return jsonify(error=f"Upload failed: {e}"), 500

    # The "filename" stored in DB is  folder_id/entry_point
    filename = f"{folder_id}/{entry_point}"
    title = (request.form.get("title") or "Untitled Game").strip()[:80]
    description = (request.form.get("description") or "").strip()[:500]
    icon = (request.form.get("icon") or "").strip()[:500]
    auto_approve = 1 if user["role"] == "admin" else 0

    with db() as conn:
        cur = conn.execute(
            "INSERT INTO games (title, description, filename, file_type, icon, uploader_id, approved) "
            "VALUES (?,?,?,?,?,?,?)",
            (title, description, filename, "folder", icon, user["id"], auto_approve)
        )
        game_id = cur.lastrowid

    return jsonify(ok=True, id=game_id, approved=bool(auto_approve), file_type="folder",
                   entry_point=entry_point)


@bp.post("/<int:game_id>/approve")
@require_role("admin")
def approve_game(game_id):
    with db() as conn:
        result = conn.execute("UPDATE games SET approved=1 WHERE id=?", (game_id,))
    if result.rowcount == 0:
        return jsonify(error="Game not found."), 404
    return jsonify(ok=True)


@bp.delete("/<int:game_id>")
@require_auth
def delete_game(game_id):
    user = current_user()
    with db() as conn:
        game = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if not game:
            return jsonify(error="Game not found."), 404
        if user["role"] != "admin" and user["id"] != game["uploader_id"]:
            return jsonify(error="You cannot delete this game."), 403

        filepath = os.path.join(UPLOAD_DIR, game["filename"])
        if game["file_type"] == "folder":
            # Remove the whole folder
            folder = os.path.join(UPLOAD_DIR, game["filename"].split("/")[0])
            shutil.rmtree(folder, ignore_errors=True)
        elif os.path.exists(filepath):
            os.remove(filepath)

        conn.execute("DELETE FROM games WHERE id=?", (game_id,))
    return jsonify(ok=True)

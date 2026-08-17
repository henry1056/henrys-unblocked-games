import os
import pty
import threading
import select
import signal
import bcrypt
from flask import Blueprint, request, jsonify, session
from flask_socketio import emit, disconnect
from db import get_user_by_id

bp = Blueprint("terminal", __name__, url_prefix="/api/terminal")

# Active PTY sessions keyed by socket session id
_sessions = {}

def _get_admin_hash():
    """Fetch the admin user's password hash from DB for terminal auth."""
    from db import get_conn
    conn = get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE role='admin' LIMIT 1").fetchone()
    conn.close()
    return row["password_hash"] if row else None

@bp.post("/auth")
def terminal_auth():
    """Verify admin password before allowing terminal access."""
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    admin_hash = _get_admin_hash()
    if not admin_hash or not bcrypt.checkpw(password.encode(), admin_hash.encode()):
        return jsonify(error="Invalid admin password."), 401
    session["terminal_authed"] = True
    return jsonify(ok=True)


def register_terminal_socket(socketio):
    """Register Socket.IO events for the terminal. Called from app.py."""

    @socketio.on("terminal:connect")
    def on_terminal_connect(data=None):
        if not session.get("terminal_authed"):
            emit("terminal:error", "Not authenticated.")
            disconnect()
            return

        sid = request.sid

        # Spawn a real PTY shell
        master_fd, slave_fd = pty.openpty()
        pid = os.fork()

        if pid == 0:
            # Child — become the shell
            os.setsid()
            import fcntl, termios, struct
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            for fd in (0, 1, 2):
                os.dup2(slave_fd, fd)
            os.close(master_fd)
            os.close(slave_fd)
            shell = os.environ.get("SHELL", "/bin/bash")
            os.execvpe(shell, [shell], {
                **os.environ,
                "TERM": "xterm-256color",
                "HOME": os.environ.get("HOME", "/root"),
            })
            os._exit(1)

        # Parent — store session and start reader thread
        os.close(slave_fd)
        _sessions[sid] = {"pid": pid, "fd": master_fd}

        def read_output():
            while True:
                try:
                    r, _, _ = select.select([master_fd], [], [], 0.04)
                    if r:
                        data = os.read(master_fd, 4096)
                        if data:
                            socketio.emit("terminal:output", data.decode("utf-8", errors="replace"), room=sid)
                except OSError:
                    break
            socketio.emit("terminal:closed", "Shell exited.", room=sid)

        t = threading.Thread(target=read_output, daemon=True)
        t.start()
        emit("terminal:ready", "Shell started.")

    @socketio.on("terminal:input")
    def on_terminal_input(data):
        if not session.get("terminal_authed"):
            return
        sid = request.sid
        sess = _sessions.get(sid)
        if sess:
            try:
                os.write(sess["fd"], data.encode("utf-8"))
            except OSError:
                pass

    @socketio.on("terminal:resize")
    def on_terminal_resize(data):
        sid = request.sid
        sess = _sessions.get(sid)
        if sess:
            import fcntl, termios, struct
            rows = data.get("rows", 24)
            cols = data.get("cols", 80)
            fcntl.ioctl(sess["fd"], termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))

    @socketio.on("disconnect")
    def on_terminal_disconnect():
        sid = request.sid
        sess = _sessions.pop(sid, None)
        if sess:
            try:
                os.kill(sess["pid"], signal.SIGKILL)
                os.waitpid(sess["pid"], os.WNOHANG)
                os.close(sess["fd"])
            except OSError:
                pass

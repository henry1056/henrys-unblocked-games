import time
from functools import wraps
from flask import session, jsonify
from db import get_user_by_id


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    row = get_user_by_id(uid)
    if row:
        return dict(row)
    return None


def is_timed_out(user):
    t = user.get("timeout_until")
    return t and t > int(time.time() * 1000)


def timeout_remaining_minutes(user):
    t = user.get("timeout_until")
    if t and t > int(time.time() * 1000):
        return max(1, int((t - int(time.time() * 1000)) / 60000))
    return None


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify(error="You must be logged in."), 401
        if user["banned"]:
            session.clear()
            return jsonify(error="This account has been banned."), 403
        return f(*args, **kwargs)
    return decorated


def require_role(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify(error="You must be logged in."), 401
            if user["banned"]:
                session.clear()
                return jsonify(error="This account has been banned."), 403
            if user["role"] not in roles:
                return jsonify(error="You do not have permission to do that."), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def block_if_timed_out(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()
        if user and is_timed_out(user):
            mins = timeout_remaining_minutes(user)
            return jsonify(error=f"You are timed out for {mins} more minute(s)."), 403
        return f(*args, **kwargs)
    return decorated

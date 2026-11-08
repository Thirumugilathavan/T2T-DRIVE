import datetime
from flask import jsonify

def success_response(data=None, meta=None, status_code=200):
    """Generates standard success response envelope."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    envelope = {
        "success": True,
        "data": data if data is not None else {},
        "error": None,
        "meta": meta or {"timestamp": now_iso}
    }
    return jsonify(envelope), status_code


def error_response(code: str, message: str, details=None, status_code=400):
    """Generates standard error response envelope."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    envelope = {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details
        },
        "meta": {"timestamp": now_iso}
    }
    return jsonify(envelope), status_code

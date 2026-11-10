"""
T2T DRIVE Frontend Delivery Routes.
Serves the single-page application (SPA) cockpit, passenger interface,
and static assets (CSS, JS, SVG, images) from the existing frontend/ directory.
Preserves all /api/* endpoints and prevents directory traversal.
"""

import os
import mimetypes
from pathlib import Path
from flask import Blueprint, send_from_directory, abort, current_app, request

# Ensure explicit MIME types across all platforms (notably Windows)
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("application/json", ".json")

frontend_bp = Blueprint("frontend", __name__)

KNOWN_SPA_SECTIONS = {
    "copilot",
    "trips",
    "finance",
    "documents",
    "settlement",
    "vehicle",
    "agent",
}


def get_frontend_dir() -> Path:
    """Resolves the absolute path to the frontend directory."""
    config_dir = current_app.config.get("FRONTEND_DIR")
    if config_dir:
        p = Path(config_dir).resolve()
        if p.is_dir():
            return p

    # Standard repository layout: <repo_root>/frontend where current_app.root_path is <repo_root>/backend/app
    app_root = Path(current_app.root_path)
    candidate = (app_root.parent.parent / "frontend").resolve()
    if candidate.is_dir():
        return candidate

    # Fallback layout: ./frontend relative to CWD
    cwd_candidate = Path("frontend").resolve()
    if cwd_candidate.is_dir():
        return cwd_candidate

    return candidate


@frontend_bp.route("/", methods=["GET"], strict_slashes=False)
@frontend_bp.route("/index.html", methods=["GET"], strict_slashes=False)
def serve_index():
    """Serves the driver cockpit SPA homepage."""
    frontend_dir = get_frontend_dir()
    index_file = frontend_dir / "index.html"
    if not index_file.is_file():
        abort(404)
    return send_from_directory(frontend_dir, "index.html", mimetype="text/html")


@frontend_bp.route("/passenger.html", methods=["GET"], strict_slashes=False)
@frontend_bp.route("/passenger", methods=["GET"], strict_slashes=False)
def serve_passenger():
    """Serves the lightweight passenger co-pilot interface."""
    frontend_dir = get_frontend_dir()
    passenger_file = frontend_dir / "passenger.html"
    if not passenger_file.is_file():
        abort(404)
    return send_from_directory(frontend_dir, "passenger.html", mimetype="text/html")


@frontend_bp.route("/health", methods=["GET"], strict_slashes=False)
def serve_root_health():
    """Root /health endpoint alias for deployment platforms and load balancers."""
    from app.routes.health_routes import health_check
    return health_check()


@frontend_bp.route("/css/<path:filename>", methods=["GET"])
def serve_css(filename):
    """Serves CSS stylesheets with proper MIME types and path validation."""
    frontend_dir = get_frontend_dir()
    css_dir = frontend_dir / "css"
    safe_path = (css_dir / filename).resolve()
    try:
        safe_path.relative_to(css_dir)
    except ValueError:
        abort(404)
    if not safe_path.is_file():
        abort(404)
    return send_from_directory(css_dir, filename, mimetype="text/css")


@frontend_bp.route("/js/<path:filename>", methods=["GET"])
def serve_js(filename):
    """Serves JavaScript application scripts with proper MIME types and path validation."""
    frontend_dir = get_frontend_dir()
    js_dir = frontend_dir / "js"
    safe_path = (js_dir / filename).resolve()
    try:
        safe_path.relative_to(js_dir)
    except ValueError:
        abort(404)
    if not safe_path.is_file():
        abort(404)
    return send_from_directory(js_dir, filename, mimetype="application/javascript")


@frontend_bp.route("/assets/<path:filename>", methods=["GET"])
def serve_assets(filename):
    """Serves static assets (SVGs, branding images, icons) with path validation."""
    frontend_dir = get_frontend_dir()
    assets_dir = frontend_dir / "assets"
    safe_path = (assets_dir / filename).resolve()
    try:
        safe_path.relative_to(assets_dir)
    except ValueError:
        abort(404)
    if not safe_path.is_file():
        abort(404)
    return send_from_directory(assets_dir, filename)


@frontend_bp.route("/<path:filename>", methods=["GET"])
def serve_static_root_or_spa(filename):
    """
    Serves root-level static assets or SPA deep-link section URLs.
    Never intercepts /api/* endpoints.
    Guards strictly against directory traversal.
    """
    # 1. Strictly bypass and reject interception of any API routes
    clean_path = filename.strip("/")
    if clean_path.startswith("api/") or clean_path == "api":
        abort(404)

    frontend_dir = get_frontend_dir()

    # 2. Support SPA deep navigation sections (e.g. /finance, /copilot)
    if clean_path in KNOWN_SPA_SECTIONS:
        return send_from_directory(frontend_dir, "index.html", mimetype="text/html")

    # 3. Check for physical file in frontend directory
    target_file = (frontend_dir / clean_path).resolve()
    try:
        # Enforce that the target file resides strictly within frontend_dir
        target_file.relative_to(frontend_dir)
    except ValueError:
        abort(404)

    if target_file.is_file():
        return send_from_directory(frontend_dir, clean_path)

    abort(404)

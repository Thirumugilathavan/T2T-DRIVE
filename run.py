"""
Root-level run entry point for T2T DRIVE.
Enables local execution directly from the repository root.
Exports 'app' and 'application'.
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app import create_app

app = create_app()
application = app

if __name__ == "__main__":
    host = app.config.get("HOST", "0.0.0.0")
    port = app.config.get("PORT", 5000)
    debug = app.config.get("DEBUG", False)
    app.run(host=host, port=port, debug=debug)

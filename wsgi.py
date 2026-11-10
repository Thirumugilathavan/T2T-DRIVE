"""
Root-level WSGI entry point for T2T DRIVE.
Enables running Gunicorn directly from the repository root without requiring --chdir.
Exports 'app' and 'application'.
"""
import sys
from pathlib import Path

# Add backend directory to sys.path so 'import app' resolves cleanly
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app import create_app

app = create_app()
application = app

if __name__ == "__main__":
    app.run()

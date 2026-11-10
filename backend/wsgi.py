"""
WSGI entry point for T2T DRIVE on Render and production application servers.
Exports 'app' and 'application' for compatibility with standard Gunicorn conventions.
"""
from app import create_app

app = create_app()
application = app

if __name__ == "__main__":
    app.run()

import pytest
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app import create_app

@pytest.fixture(scope="session")
def app():
    """Session-wide test Flask application with testing configuration."""
    os.environ["FLASK_ENV"] = "testing"
    test_app = create_app("testing")
    yield test_app


@pytest.fixture
def client(app):
    """Test client for invoking Flask HTTP routes."""
    return app.test_client()


@pytest.fixture
def db(app):
    """Provides direct access to the in-memory test database."""
    return app.extensions["db"]

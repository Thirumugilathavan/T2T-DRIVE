import os
import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(Exception):
    """Raised when a database operation is attempted while MongoDB is disconnected."""
    pass


class DisconnectedCollection:
    """Null object for a MongoDB collection when the database is unavailable."""
    def __init__(self, name: str):
        self.name = name

    def __getattr__(self, method: str):
        def _fail(*args, **kwargs):
            raise DatabaseUnavailableError(
                f"Database is currently unavailable: cannot execute '{method}' on collection '{self.name}'. "
                "Please configure MONGODB_URI in Render dashboard."
            )
        return _fail

    def __getitem__(self, name: str):
        return self


class DisconnectedDatabase:
    """Null object for MongoDB database when disconnected. Prevents startup AttributeError."""
    def __getattr__(self, name: str):
        return DisconnectedCollection(name)

    def __getitem__(self, name: str):
        return DisconnectedCollection(name)


class DatabaseManager:
    """Manages the MongoDB Atlas connection with fallback and health checks."""

    def __init__(self):
        self.client = None
        self.db = None
        self._is_mock = False

    def init_app(self, app):
        uri = app.config.get("MONGODB_URI", "mongodb://localhost:27017/t2t_drive")
        db_name = app.config.get("DB_NAME", "t2t_drive")
        testing = app.config.get("TESTING", False)

        # 1. Dedicated Isolated Real Test Database (if explicitly configured)
        test_live_uri = app.config.get("TEST_LIVE_MONGODB_URI") or os.getenv("TEST_LIVE_MONGODB_URI")
        if testing and test_live_uri and not uri.startswith("mongomock://"):
            parsed_test_db = app.config.get("DB_NAME", "t2t_drive_test")
            if parsed_test_db.lower() in ("t2t_drive", "production", "prod", "live"):
                parsed_test_db = "t2t_drive_integration_test"
            try:
                self.client = MongoClient(test_live_uri, serverSelectionTimeoutMS=3000)
                self.client.admin.command("ping")
                self.db = self.client[parsed_test_db]
                self._is_mock = False
                logger.info("Connected to dedicated test live MongoDB database: %s", parsed_test_db)
                return
            except Exception as err:
                logger.error("Failed to connect to TEST_LIVE_MONGODB_URI: %s", err)
                raise ConnectionError(f"Failed to connect to TEST_LIVE_MONGODB_URI: {err}")

        # 2. In-Memory Mock Testing (Default for testing when no TEST_LIVE_MONGODB_URI is provided)
        if testing or uri.startswith("mongomock://"):
            try:
                import mongomock
                self.client = mongomock.MongoClient()
                self.db = self.client[db_name]
                self._is_mock = True
                logger.info("[MOCK] Connected to in-memory mongomock database: %s", db_name)
                return
            except ImportError:
                logger.warning("mongomock not installed, attempting standard MongoClient for testing.")

        # Enforce Production Database Requirement: Disallow silent mock fallback on Render
        is_render = bool(os.getenv("RENDER")) or app.config.get("ENV", "development").lower() == "production"
        if is_render and not testing and ("localhost" in uri or "127.0.0.1" in uri):
            logger.warning(
                "MONGODB NOTICE: URI points to localhost on Render (%s). Live Atlas connection is not configured. "
                "Set MONGODB_URI or MONGO_URI in Render dashboard. Mock database fallback is disabled.",
                uri
            )
            self.db = DisconnectedDatabase()
            self._is_mock = False
            return

        try:
            # Set a 3-second server selection timeout to avoid hanging if DB is unreachable
            self.client = MongoClient(uri, serverSelectionTimeoutMS=3000)
            # Trigger server selection check
            self.client.admin.command("ping")
            self.db = self.client[db_name]
            self._is_mock = False
            logger.info("Successfully connected to MongoDB Atlas database: %s", db_name)
        except (ConnectionFailure, ServerSelectionTimeoutError) as err:
            if is_render:
                self.db = DisconnectedDatabase()
                self._is_mock = False
                logger.error(
                    "MongoDB connection failed on Render: %s. "
                    "Mock database fallback is disabled on Render. Atlas database is disconnected.",
                    err
                )
                return

            logger.warning("Could not connect to live MongoDB (%s). Falling back to mock database for development.", err)
            try:
                import mongomock
                self.client = mongomock.MongoClient()
                self.db = self.client[db_name]
                self._is_mock = True
                logger.info("[MOCK] Fallback: initialized mongomock database.")
            except ImportError:
                self.db = DisconnectedDatabase()
                logger.error("No MongoDB or mongomock available! Database operations will fail.")

    def get_db(self):
        if self.db is None:
            return DisconnectedDatabase()
        return self.db

    def is_connected(self):
        if self.db is None or isinstance(self.db, DisconnectedDatabase):
            return False
        if self._is_mock:
            return True
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    def is_mock(self):
        return self._is_mock

    def close(self):
        if self.client:
            self.client.close()


db_manager = DatabaseManager()

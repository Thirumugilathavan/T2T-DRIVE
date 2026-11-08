import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)

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

        try:
            # Set a 3-second server selection timeout to avoid hanging if DB is unreachable
            self.client = MongoClient(uri, serverSelectionTimeoutMS=3000)
            # Trigger server selection check
            self.client.admin.command("ping")
            self.db = self.client[db_name]
            self._is_mock = False
            logger.info("Successfully connected to MongoDB Atlas database: %s", db_name)
        except (ConnectionFailure, ServerSelectionTimeoutError) as err:
            env = app.config.get("ENV", "development").lower()
            if env == "production":
                self.db = None
                self._is_mock = False
                logger.critical(
                    "FATAL: Failed to connect to MongoDB Atlas in PRODUCTION environment: %s. "
                    "Automatic mock fallback is strictly disabled in production.",
                    err
                )
                raise ConnectionError(f"Production database connection failed: {err}")

            logger.warning("Could not connect to live MongoDB (%s). Falling back to mock database for development.", err)
            try:
                import mongomock
                self.client = mongomock.MongoClient()
                self.db = self.client[db_name]
                self._is_mock = True
                logger.info("[MOCK] Fallback: initialized mongomock database.")
            except ImportError:
                # If neither mongomock nor real mongo works, keep client for error reporting
                self.db = None
                logger.error("No MongoDB or mongomock available! Database operations will fail.")

    def get_db(self):
        return self.db

    def is_connected(self):
        if self.db is None:
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

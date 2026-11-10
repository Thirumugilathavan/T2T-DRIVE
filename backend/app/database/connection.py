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


def diagnose_mongo_error(err: Exception, uri: str) -> dict:
    """
    Analyzes MongoDB connection failures and produces safe, actionable diagnostics
    without logging credentials or secret strings.
    """
    err_str = str(err)
    err_lower = err_str.lower()

    if "tlsv1_alert_internal_error" in err_lower or "ssl handshake failed" in err_lower:
        category = "TLS_OR_IP_FIREWALL_BLOCK"
        action = (
            "Atlas dropped the TLS handshake. This occurs when the Render outbound IP is not on the Atlas Network Access whitelist. "
            "REQUIRED: In MongoDB Atlas Dashboard -> Network Access -> Add IP Address -> Select 'Allow Access from Anywhere' (0.0.0.0/0). "
            "Render uses dynamic outbound IP addresses that will be rejected without 0.0.0.0/0."
        )
    elif "bad auth" in err_lower or "authentication failed" in err_lower:
        category = "AUTHENTICATION_FAILED"
        action = (
            "Atlas rejected database user credentials. "
            "Verify username and password in MONGODB_URI. If the password contains special characters (like '@', ':', '/', '%'), they must be URL-encoded (e.g. '@' becomes '%40')."
        )
    elif "srv" in err_lower or "nameservers failed" in err_lower or "nodename nor servname provided" in err_lower:
        category = "DNS_RESOLUTION_FAILURE"
        action = (
            "Failed to resolve MongoDB Atlas SRV host. "
            "Check cluster hostname in MONGODB_URI and verify dnspython is installed."
        )
    elif "timed out" in err_lower or "serverselectiontimeouterror" in err_lower:
        category = "CONNECTION_TIMEOUT"
        action = (
            "Connection to MongoDB Atlas timed out. "
            "Check that your Atlas cluster is active (not paused) and port 27017 is reachable."
        )
    else:
        category = "CONNECTION_ERROR"
        action = "Check MongoDB Atlas cluster status and connection string format."

    # Mask credentials: show only scheme and host
    masked_target = "unknown"
    if "@" in uri:
        parts = uri.split("@", 1)
        scheme_prefix = parts[0].split("://")[0] + "://" if "://" in parts[0] else "mongodb+srv://"
        host = parts[1].split("/")[0].split("?")[0]
        masked_target = f"{scheme_prefix}***:***@{host}"
    elif "://" in uri:
        scheme = uri.split("://")[0]
        masked_target = f"{scheme}://***"

    return {
        "category": category,
        "action": action,
        "target": masked_target,
        "summary": err_str[:250]
    }


class DatabaseManager:
    """Manages the MongoDB Atlas connection with fallback and health checks."""

    def __init__(self):
        self.client = None
        self.db = None
        self._is_mock = False
        self._last_diagnostic = None

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
                self._last_diagnostic = None
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
                self._last_diagnostic = None
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
            self._last_diagnostic = {
                "category": "LOCAL_URI_ON_RENDER",
                "action": "Set MONGODB_URI in Render dashboard with your live Atlas connection string (mongodb+srv://...).",
                "target": "localhost:27017",
                "summary": "Localhost URI is forbidden in production on Render."
            }
            return

        # Determine TLS and Certificate Authority Configuration
        is_tls = uri.startswith("mongodb+srv://") or "tls=true" in uri.lower() or "ssl=true" in uri.lower()
        client_kwargs = {
            "serverSelectionTimeoutMS": 5000,
            "connectTimeoutMS": 5000,
            "socketTimeoutMS": 5000,
        }
        if is_tls:
            try:
                import certifi
                client_kwargs["tlsCAFile"] = certifi.where()
            except ImportError:
                logger.warning("certifi package not available; using system CA trust store.")

        try:
            self.client = MongoClient(uri, **client_kwargs)
            # Trigger server selection check
            self.client.admin.command("ping")
            self.db = self.client[db_name]
            self._is_mock = False
            self._last_diagnostic = None
            logger.info("Successfully connected to MongoDB Atlas database: %s", db_name)
        except (ConnectionFailure, ServerSelectionTimeoutError) as err:
            diagnostic = diagnose_mongo_error(err, uri)
            self._last_diagnostic = diagnostic
            if is_render:
                self.db = DisconnectedDatabase()
                self._is_mock = False
                logger.error(
                    "[MONGODB ATLAS DIAGNOSTICS] Connection failed: category=%s, target=%s. Action: %s (Details: %s)",
                    diagnostic["category"],
                    diagnostic["target"],
                    diagnostic["action"],
                    diagnostic["summary"]
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

    def get_last_diagnostic(self):
        return self._last_diagnostic

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

"""
T2T DRIVE Application Factory.
Configures Flask, CORS, MongoDB, indexes, authentication, core financial services,
Phase 3 LangGraph Conversational Agent, and Phase 4 Voice Integration (Prisma & Timbre).
"""

import logging
from flask import Flask
from flask_cors import CORS
from app.config import get_config, config_by_name
from app.database.connection import db_manager
from app.database.indexes import ensure_indexes
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from app.services.idempotency_service import IdempotencyService
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.settlement_service import SettlementService
from app.services.pending_action_service import PendingActionService
from app.services.summary_service import SummaryService
from app.utils.responses import error_response

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger(__name__)


def create_app(config_name=None):
    """
    Application Factory Pattern.
    Instantiates Flask, sets up CORS, database connections, blueprints, and error handlers.
    """
    app = Flask(__name__)

    # 1. Load Configuration
    config_class = config_by_name.get(config_name) if config_name else get_config()
    app.config.from_object(config_class)
    if hasattr(config_class, "validate"):
        config_class.validate()

    # 2. Configure CORS with restricted origins
    allowed_origins = app.config.get("ALLOWED_ORIGINS", ["*"])
    CORS(
        app,
        resources={r"/api/*": {"origins": allowed_origins}},
        supports_credentials=True
    )
    logger.info("Configured CORS for origins: %s", allowed_origins)

    # 3. Initialize Database Manager & Ensure Indexes
    db_manager.init_app(app)
    db = db_manager.get_db()
    if db is not None:
        ensure_indexes(db)

    # 4. Initialize Core Foundation & Financial Services
    auth_service = AuthService(db=db, config=app.config)
    audit_service = AuditService(db=db)
    idempotency_service = IdempotencyService(db=db, audit_service=audit_service)
    transaction_repository = TransactionRepository(db=db)
    ledger_service = LedgerService(repo=transaction_repository, audit_service=audit_service)
    settlement_service = SettlementService(db=db, repo=transaction_repository, audit_service=audit_service)
    pending_action_service = PendingActionService(
        db=db,
        ledger_service=ledger_service,
        settlement_service=settlement_service,
        idempotency_service=idempotency_service,
        audit_service=audit_service
    )
    summary_service = SummaryService(repo=transaction_repository)

    # 4.5 Initialize Conversational Agent (Phase 3)
    from app.agent.service import AgentService
    agent_service = AgentService(
        db=db,
        pending_action_service=pending_action_service,
        ledger_service=ledger_service,
        summary_service=summary_service,
        settlement_service=settlement_service
    )

    # 4.6 Initialize Voice Integration (Phase 4)
    from app.voice import (
        AudioValidator,
        AudioPreprocessor,
        PrismaAdapter,
        MockPrismaAdapter,
        TimbreAdapter,
        MockTimbreAdapter,
        VoiceService
    )

    voice_mode = app.config.get("VOICE_PROVIDER_MODE", "mock").lower()
    gnani_key = app.config.get("GNANI_API_KEY", "")

    if voice_mode == "live" and gnani_key:
        logger.info("[LIVE] Initializing live Gnani Prisma STT and Timbre TTS adapters.")
        prisma_adapter = PrismaAdapter(
            api_key=gnani_key,
            endpoint_url=app.config.get("GNANI_PRISMA_ENDPOINT")
        )
        timbre_adapter = TimbreAdapter(
            api_key=gnani_key,
            endpoint_url=app.config.get("GNANI_TIMBRE_ENDPOINT")
        )
    else:
        logger.info("[MOCK] Initializing mock Gnani Prisma STT and Timbre TTS adapters.")
        prisma_adapter = MockPrismaAdapter()
        timbre_adapter = MockTimbreAdapter()

    audio_validator = AudioValidator(
        max_upload_mb=app.config.get("VOICE_MAX_UPLOAD_MB", 10),
        temp_dir=app.config.get("VOICE_TEMP_DIRECTORY") or None
    )
    audio_preprocessor = AudioPreprocessor(
        max_duration_seconds=float(app.config.get("VOICE_MAX_DURATION_SECONDS", 60))
    )

    voice_service = VoiceService(
        prisma_adapter=prisma_adapter,
        timbre_adapter=timbre_adapter,
        agent_service=agent_service,
        validator=audio_validator,
        preprocessor=audio_preprocessor
    )

    # Store in app extensions for dependency injection in routes
    app.extensions["db_manager"] = db_manager
    app.extensions["db"] = db
    app.extensions["auth_service"] = auth_service
    app.extensions["audit_service"] = audit_service
    app.extensions["idempotency_service"] = idempotency_service
    app.extensions["transaction_repository"] = transaction_repository
    app.extensions["ledger_service"] = ledger_service
    app.extensions["settlement_service"] = settlement_service
    app.extensions["pending_action_service"] = pending_action_service
    app.extensions["summary_service"] = summary_service
    app.extensions["agent_service"] = agent_service
    app.extensions["prisma_adapter"] = prisma_adapter
    app.extensions["timbre_adapter"] = timbre_adapter
    app.extensions["audio_validator"] = audio_validator
    app.extensions["audio_preprocessor"] = audio_preprocessor
    app.extensions["voice_service"] = voice_service

    # 5. Register Blueprints
    from app.routes.health_routes import health_bp
    from app.routes.auth_routes import auth_bp
    from app.routes.transaction_routes import transaction_bp
    from app.routes.pending_action_routes import pending_action_bp
    from app.routes.finance_routes import finance_bp
    from app.routes.settlement_routes import settlement_bp
    from app.routes.agent_routes import agent_bp
    from app.routes.voice_routes import voice_bp, speech_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(transaction_bp)
    app.register_blueprint(pending_action_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(settlement_bp)
    app.register_blueprint(agent_bp)
    app.register_blueprint(voice_bp)
    app.register_blueprint(speech_bp)

    # 6. Centralized Error Handlers
    register_error_handlers(app)

    logger.info("T2T DRIVE Flask application factory initialized successfully with Phase 4 Voice Integration (Prisma & Timbre).")
    return app


def register_error_handlers(app):
    """Centralized HTTP exception handlers returning unified JSON envelopes."""

    @app.errorhandler(400)
    def bad_request(error):
        return error_response(
            code="BAD_REQUEST",
            message=str(error.description) if hasattr(error, "description") else "Malformed request.",
            status_code=400
        )

    @app.errorhandler(404)
    def not_found(error):
        return error_response(
            code="NOT_FOUND",
            message="The requested endpoint does not exist.",
            status_code=404
        )

    @app.errorhandler(405)
    def method_not_allowed(error):
        return error_response(
            code="METHOD_NOT_ALLOWED",
            message="HTTP method not allowed for this endpoint.",
            status_code=405
        )

    @app.errorhandler(429)
    def ratelimit_handler(error):
        return error_response(
            code="RATE_LIMIT_EXCEEDED",
            message="Too many requests. Please slow down.",
            status_code=429
        )

    @app.errorhandler(500)
    def internal_error(error):
        logger.error("Internal Server Error: %s", error, exc_info=True)
        return error_response(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred. Please try again later.",
            status_code=500
        )

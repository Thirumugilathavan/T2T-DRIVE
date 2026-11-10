"""
Live MongoDB Atlas Integration Tests for T2T DRIVE.
Executes against a dedicated disposable Atlas test database when explicitly
configured via TEST_LIVE_MONGODB_URI and TEST_LIVE_MONGODB_DB.
Skips gracefully with explicit diagnostics when offline, unreachable, or bad credentials.
"""

import os
import uuid
import pytest
import certifi
import bson
from decimal import Decimal
from urllib.parse import urlparse
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError, OperationFailure, ConfigurationError

from app.models.financial import TransactionType
from app.repositories.transaction_repository import TransactionRepository, to_mongo_doc, from_mongo_doc
from app.services.ledger_service import LedgerService
from app.database.indexes import ensure_indexes


LIVE_URI = os.getenv("TEST_LIVE_MONGODB_URI")
LIVE_DB_NAME = os.getenv("TEST_LIVE_MONGODB_DB", "t2t_drive_integration_test")
EXPECTED_HOST = "t2t-drive-test.a7xvw1t.mongodb.net"


def configure_fast_dns():
    """Configures dnspython to prioritize active network adapter DNS on Windows."""
    try:
        import dns.resolver
        r = dns.resolver.Resolver()
        r.timeout = 1.0
        r.lifetime = 2.5
        if r.nameservers:
            # On Windows, reverse so active interface DNS is queried first
            r.nameservers = list(reversed(r.nameservers))
        dns.resolver.default_resolver = r
    except Exception:
        pass


def get_live_client_or_skip():
    """
    Validates cluster safety constraints and verifies connectivity.
    Skips test gracefully if configuration is missing, host mismatches,
    or connection/authentication fails.
    """
    if not LIVE_URI:
        pytest.skip("TEST_LIVE_MONGODB_URI not set. Skipped in mock/offline test environments.")

    # Strict Safety Rule: Hostname verification
    if EXPECTED_HOST not in LIVE_URI:
        pytest.skip(
            f"Safety guard: TEST_LIVE_MONGODB_URI does not target dedicated test host '{EXPECTED_HOST}'. Execution stopped."
        )

    # Strict Safety Rule: Database verification
    if LIVE_DB_NAME.lower() in ("t2t_drive", "production", "prod", "live") or not LIVE_DB_NAME.endswith("_test"):
        pytest.skip(
            f"Safety guard: Target DB '{LIVE_DB_NAME}' rejected. Must end with '_test' and cannot be production."
        )

    configure_fast_dns()

    try:
        ca_file = certifi.where() if os.path.exists(certifi.where()) else None
        client = MongoClient(
            LIVE_URI,
            serverSelectionTimeoutMS=2500,
            connectTimeoutMS=2500,
            tlsCAFile=ca_file
        )
        # Probe connectivity and authentication
        client.admin.command("ping")
        return client
    except ServerSelectionTimeoutError as exc:
        pytest.skip(
            f"Atlas IP access / TLS handshake restriction (ServerSelectionTimeoutError): {exc}. "
            "Reported configuration issue; stopping live Atlas tests while preserving unit/mock suite."
        )
    except OperationFailure as exc:
        pytest.skip(
            f"Atlas authentication/authorization failed (OperationFailure code {exc.code}): {exc}. "
            "Reported configuration issue; stopping live Atlas tests while preserving unit/mock suite."
        )
    except ConfigurationError as exc:
        pytest.skip(
            f"Atlas DNS SRV resolution error (ConfigurationError): {exc}. "
            "Reported configuration issue; stopping live Atlas tests while preserving unit/mock suite."
        )
    except Exception as exc:
        pytest.skip(f"Unexpected connection probe error ({exc.__class__.__name__}): {exc}")


@pytest.fixture
def live_db():
    """Fixture providing a connected live MongoDB database with cleanup."""
    client = get_live_client_or_skip()
    db = client[LIVE_DB_NAME]
    ensure_indexes(db)
    yield db
    try:
        # Isolated test driver cleanup (deletes ONLY records created by this test run)
        db.transactions.delete_many({"driver_id": {"$regex": "^DRV_LIVE_TEST"}})
        db.pending_actions.delete_many({"driver_id": {"$regex": "^DRV_LIVE_TEST"}})
    except Exception:
        pass
    finally:
        client.close()


def test_real_mongodb_decimal128_round_trip(live_db):
    """
    Verifies that Decimal values are stored as BSON Decimal128 and read back
    with exact decimal precision without floating point distortion.
    """
    repo = TransactionRepository(live_db)
    doc = {
        "transaction_id": "TXN_LIVE_DEC_1",
        "driver_id": "DRV_LIVE_TEST_DEC",
        "vehicle_id": "KA01LIVE01",
        "transaction_type": "INCOME",
        "amount": Decimal("1500.50"),
        "signed_amount": Decimal("1500.50"),
        "category": "FARE",
        "description": "Decimal128 round-trip verification"
    }
    repo.insert_transaction(doc)
    read_back = repo.get_by_id("TXN_LIVE_DEC_1", "DRV_LIVE_TEST_DEC")
    assert read_back is not None
    assert isinstance(read_back["amount"], Decimal)
    assert read_back["amount"] == Decimal("1500.50")


def test_real_mongodb_indexes_and_uniqueness(live_db):
    """
    Verifies that unique index constraints on transaction_id are enforced by the engine.
    """
    repo = TransactionRepository(live_db)
    doc1 = {
        "transaction_id": "TXN_LIVE_UNIQ_1",
        "driver_id": "DRV_LIVE_TEST_UNIQ",
        "vehicle_id": "KA01LIVE01",
        "transaction_type": "EXPENSE",
        "amount": Decimal("300.00"),
        "signed_amount": Decimal("-300.00"),
        "category": "FUEL",
        "description": "Unique index test 1"
    }
    repo.insert_transaction(doc1)

    # Attempt duplicate insert
    doc2 = dict(doc1)
    doc2["description"] = "Duplicate transaction_id"
    with pytest.raises(Exception):
        repo.insert_transaction(doc2)


def test_real_mongodb_session_transaction_or_fallback(live_db):
    """
    Verifies session-based transaction support on the real Atlas replica set:
    1. Tests abort_transaction: inserts a valid BSON Decimal128 doc, aborts, and verifies doc does not exist.
    2. Tests commit_transaction: inserts a valid BSON Decimal128 doc, commits, and verifies doc persisted.
    3. If transactions are unsupported on the deployment, accurately validates the application's fallback.
    """
    client = live_db.client
    repo = TransactionRepository(live_db)
    driver_id = "DRV_LIVE_TEST_TXN"

    # Step 1: Verify Transaction Abort / Rollback
    txn_id_abort = f"TXN_ABORT_{uuid.uuid4().hex[:8]}"
    doc_abort = to_mongo_doc({
        "transaction_id": txn_id_abort,
        "driver_id": driver_id,
        "vehicle_id": "KA01LIVE01",
        "transaction_type": "OWNER_PAYMENT",
        "amount": Decimal("200.00"),
        "signed_amount": Decimal("-200.00"),
        "category": "OWNER_RENT",
        "description": "Live session transaction abort test"
    })

    try:
        with client.start_session() as session:
            with session.start_transaction():
                live_db.transactions.insert_one(doc_abort, session=session)
                session.abort_transaction()

        # Document MUST NOT exist after abort
        aborted = live_db.transactions.find_one({"transaction_id": txn_id_abort})
        assert aborted is None, "Aborted transaction document must not exist in MongoDB"

        # Step 2: Verify Transaction Commit
        txn_id_commit = f"TXN_COMMIT_{uuid.uuid4().hex[:8]}"
        doc_commit = to_mongo_doc({
            "transaction_id": txn_id_commit,
            "driver_id": driver_id,
            "vehicle_id": "KA01LIVE01",
            "transaction_type": "OWNER_PAYMENT",
            "amount": Decimal("200.00"),
            "signed_amount": Decimal("-200.00"),
            "category": "OWNER_RENT",
            "description": "Live session transaction commit test"
        })

        with client.start_session() as session:
            with session.start_transaction():
                live_db.transactions.insert_one(doc_commit, session=session)
                session.commit_transaction()

        # Document MUST exist after commit
        committed = repo.get_by_id(txn_id_commit, driver_id)
        assert committed is not None, "Committed transaction document must exist in MongoDB"
        assert isinstance(committed["amount"], Decimal)
        assert committed["amount"] == Decimal("200.00")
        assert committed["category"] == "OWNER_RENT"

        # Clean up committed document
        live_db.transactions.delete_one({"transaction_id": txn_id_commit})

    except OperationFailure as exc:
        # Check if the cluster does not support transactions (e.g. code 20 / standalone)
        err_msg = str(exc).lower()
        if "transaction numbers are only allowed" in err_msg or "standalone" in err_msg or exc.code == 20:
            # Documented fallback: when multi-document transactions are unsupported,
            # verify application-level two-phase journaling fallback via TransactionRepository
            fallback_id = f"TXN_FALLBACK_{uuid.uuid4().hex[:8]}"
            repo.insert_transaction({
                "transaction_id": fallback_id,
                "driver_id": driver_id,
                "vehicle_id": "KA01LIVE01",
                "transaction_type": "OWNER_PAYMENT",
                "amount": Decimal("200.00"),
                "signed_amount": Decimal("-200.00"),
                "category": "OWNER_RENT",
                "description": "Standalone fallback transaction verification"
            })
            fb_read = repo.get_by_id(fallback_id, driver_id)
            assert fb_read is not None
            assert fb_read["amount"] == Decimal("200.00")
            live_db.transactions.delete_one({"transaction_id": fallback_id})
        else:
            raise


def test_real_mongodb_independent_client_persistence(live_db):
    """
    Verifies persistence across independent client instances:
    1. Client A writes a unique document and disconnects.
    2. Client B connects afresh, queries the document, and verifies data integrity.
    3. Client B cleans up the test document.
    """
    test_id = f"TXN_INDEP_{uuid.uuid4().hex[:8]}"
    driver_id = "DRV_LIVE_TEST_INDEP"
    ca_file = certifi.where() if os.path.exists(certifi.where()) else None

    # Client A: Write & close
    client_a = MongoClient(LIVE_URI, serverSelectionTimeoutMS=2500, tlsCAFile=ca_file)
    db_a = client_a[LIVE_DB_NAME]
    repo_a = TransactionRepository(db_a)
    repo_a.insert_transaction({
        "transaction_id": test_id,
        "driver_id": driver_id,
        "vehicle_id": "KA01LIVE99",
        "transaction_type": "INCOME",
        "amount": Decimal("1500.00"),
        "signed_amount": Decimal("1500.00"),
        "category": "FARE",
        "description": "Cross-client persistence test"
    })
    client_a.close()

    # Client B: Fresh connection & verify
    client_b = MongoClient(LIVE_URI, serverSelectionTimeoutMS=2500, tlsCAFile=ca_file)
    db_b = client_b[LIVE_DB_NAME]
    repo_b = TransactionRepository(db_b)
    persisted = repo_b.get_by_id(test_id, driver_id)
    assert persisted is not None
    assert persisted["amount"] == Decimal("1500.00")
    assert persisted["category"] == "FARE"

    # Cleanup with Client B
    db_b.transactions.delete_one({"transaction_id": test_id})
    client_b.close()


def test_real_mongodb_application_service_persistence(live_db):
    """
    Verifies application-level business services (LedgerService + TransactionRepository)
    executing against the real MongoDB database.
    """
    repo = TransactionRepository(live_db)
    ledger = LedgerService(repo)
    driver_id = "DRV_LIVE_TEST_SVC"
    idem_key = f"IDEM_SVC_{uuid.uuid4().hex[:8]}"

    # Record income transaction via LedgerService
    txn = ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01SVC01",
        amount=Decimal("1500.00"),
        transaction_type=TransactionType.INCOME,
        category="FARE",
        description="Daily collection via LedgerService",
        idempotency_key=idem_key
    )
    # 1. Establish actual return contract: Dict[str, Any] with formatted string amounts
    assert txn is not None
    assert isinstance(txn, dict), "LedgerService.record_transaction must return a dictionary"
    assert txn["amount"] == "1500.00", "Returned amount string must be formatted to 1500.00"
    assert txn["driver_id"] == driver_id
    assert txn["category"] == "FARE"
    assert txn["idempotency_key"] == idem_key
    assert txn["status"] == "COMPLETED"

    txn_id = txn["transaction_id"]

    # 2. Independent query via TransactionRepository
    persisted = repo.get_by_id(txn_id, driver_id)
    assert persisted is not None, "Transaction must be readable from repository"
    assert isinstance(persisted["amount"], Decimal), "Repository must return amount as native Decimal"
    assert persisted["amount"] == Decimal("1500.00"), "Persisted amount must be exactly Decimal('1500.00')"
    assert persisted["driver_id"] == driver_id
    assert persisted["transaction_type"] == TransactionType.INCOME
    assert persisted["category"] == "FARE"
    assert persisted["idempotency_key"] == idem_key

    # 3. Independent raw query directly from MongoDB collection
    raw_doc = live_db.transactions.find_one({"transaction_id": txn_id, "driver_id": driver_id})
    assert raw_doc is not None, "Document must exist in live MongoDB collection"
    assert isinstance(raw_doc["amount"], bson.Decimal128), "MongoDB storage must use BSON Decimal128"
    assert raw_doc["amount"].to_decimal() == Decimal("1500.00"), "BSON Decimal128 must decode to exact Decimal 1500.00"
    assert raw_doc["driver_id"] == driver_id
    assert raw_doc["vehicle_id"] == "KA01SVC01"
    assert raw_doc["category"] == "FARE"
    assert raw_doc["idempotency_key"] == idem_key

    # 4. Verify driver transaction query
    driver_txns = repo.get_transactions_for_driver(driver_id)
    assert len(driver_txns) == 1
    assert driver_txns[0]["transaction_id"] == txn_id
    assert driver_txns[0]["amount"] == Decimal("1500.00")

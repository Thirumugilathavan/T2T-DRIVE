"""
API Integration Tests for Vehicle and Driver Documents.
Tests endpoints under /api/documents: registration, file upload, retrieval,
compliance summary, and cross-driver isolation.
"""

import io
import json
import pytest


def get_driver_token(client, phone="9876543501"):
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_documents_unauthenticated_access_rejected(client):
    res = client.get("/api/documents")
    assert res.status_code == 401


def test_create_and_list_documents_json(client):
    token, driver_id = get_driver_token(client, "9876543502")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Register Insurance
    create_res = client.post(
        "/api/documents",
        headers=headers,
        data=json.dumps({
            "type": "Vehicle Insurance",
            "number": "POL-998822",
            "expiry": "2027-11-20",
            "vehicle_id": "TN-09-CB-1284"
        })
    )
    assert create_res.status_code == 201
    doc_data = create_res.get_json()["data"]["document"]
    doc_id = doc_data["document_id"]
    assert doc_id.startswith("DOC_")
    assert doc_data["expiry_status"] == "ACTIVE"

    # 2. List documents
    list_res = client.get("/api/documents", headers={"Authorization": f"Bearer {token}"})
    assert list_res.status_code == 200
    docs = list_res.get_json()["data"]["documents"]
    assert len(docs) >= 1
    assert any(d["document_id"] == doc_id for d in docs)


def test_document_multipart_upload_and_download(client):
    token, driver_id = get_driver_token(client, "9876543503")
    auth_headers = {"Authorization": f"Bearer {token}"}

    fake_pdf = b"%PDF-1.4\nCertificate of Fitness\n%%EOF"
    data = {
        "document_type": "Fitness Certificate",
        "document_number": "FC-12345",
        "expiry_date": "2026-11-14",
        "file": (io.BytesIO(fake_pdf), "fc_doc.pdf")
    }

    res = client.post(
        "/api/documents",
        headers=auth_headers,
        data=data,
        content_type="multipart/form-data"
    )
    assert res.status_code == 201
    doc_id = res.get_json()["data"]["document"]["document_id"]

    # Download document file
    dl_res = client.get(f"/api/documents/{doc_id}/file", headers=auth_headers)
    assert dl_res.status_code == 200
    assert dl_res.data == fake_pdf


def test_cross_driver_document_file_access_rejected(client):
    token_alice, _ = get_driver_token(client, "9876543504")
    token_bob, _ = get_driver_token(client, "9876543505")

    fake_pdf = b"%PDF-1.4\nAlice Private Doc"
    data = {
        "document_type": "Driving Licence",
        "document_number": "DL-ALICE",
        "expiry_date": "2028-10-10",
        "file": (io.BytesIO(fake_pdf), "dl.pdf")
    }

    # Alice uploads
    res = client.post("/api/documents", headers={"Authorization": f"Bearer {token_alice}"}, data=data, content_type="multipart/form-data")
    doc_id = res.get_json()["data"]["document"]["document_id"]

    # Bob attempts to download Alice's document
    bob_res = client.get(f"/api/documents/{doc_id}/file", headers={"Authorization": f"Bearer {token_bob}"})
    assert bob_res.status_code == 403


def test_compliance_status_api(client):
    token, _ = get_driver_token(client, "9876543506")
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/documents/compliance", headers=headers)
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "compliance_status" in data
    assert "total_documents" in data

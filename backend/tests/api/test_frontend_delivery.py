"""
Automated Integration Tests for Unified Frontend Delivery and API Routing.
Verifies that:
1. Flask serves frontend index.html at '/' and '/index.html'.
2. Passenger interface is served at '/passenger.html' and '/passenger'.
3. Static assets (CSS, JS, SVG) are served with correct Content-Type headers.
4. SPA deep routes serve index.html.
5. Directory traversal attacks are blocked.
6. All existing /api/* endpoints are preserved and unknown /api/* returns 404 JSON.
7. Frontend api.js uses same-origin relative URLs without hardcoded localhost.
"""

import pytest
from app import create_app


@pytest.fixture(scope="module")
def app_client():
    app = create_app("testing")
    with app.test_client() as client:
        yield client


class TestFrontendDelivery:
    """Test suite for Flask frontend delivery and static asset serving."""

    def test_serve_homepage_root(self, app_client):
        """Root '/' must serve the driver cockpit single-page app."""
        response = app_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("Content-Type", "")
        html = response.get_data(as_text=True)
        assert "T2T DRIVE" in html
        assert "app-container" in html
        assert 'src="js/api.js"' in html
        assert 'href="css/style.css"' in html

    def test_serve_index_html(self, app_client):
        """Direct access to '/index.html' must return the driver dashboard."""
        response = app_client.get("/index.html")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("Content-Type", "")
        html = response.get_data(as_text=True)
        assert "T2T DRIVE" in html
        assert "brand-badge" in html

    def test_serve_passenger_html(self, app_client):
        """'/passenger.html' must serve the passenger co-pilot interface."""
        response = app_client.get("/passenger.html")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("Content-Type", "")
        html = response.get_data(as_text=True)
        assert "Passenger Trip Co-Pilot" in html
        assert "pickupText" in html
        assert "destinationText" in html

    def test_serve_passenger_clean_route(self, app_client):
        """'/passenger' alias must serve the passenger co-pilot interface."""
        for path in ["/passenger", "/passenger/"]:
            response = app_client.get(path)
            assert response.status_code == 200, f"Failed for {path}"
            assert "text/html" in response.headers.get("Content-Type", "")
            html = response.get_data(as_text=True)
            assert "Passenger Trip Co-Pilot" in html

    def test_passenger_with_query_params(self, app_client):
        """Passenger URL with trip_id and token query params must return 200."""
        response = app_client.get("/passenger.html?trip_id=TRIP_TEST_999&token=test_tok_sec")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("Content-Type", "")

    def test_serve_css_stylesheets(self, app_client):
        """CSS stylesheets must be served with 'text/css' Content-Type."""
        for css_file in ["style.css", "responsive.css"]:
            res = app_client.get(f"/css/{css_file}")
            assert res.status_code == 200, f"Failed to serve /css/{css_file}"
            assert "text/css" in res.headers.get("Content-Type", "")
            css_content = res.get_data(as_text=True)
            assert len(css_content) > 100

    def test_serve_javascript_assets(self, app_client):
        """JavaScript files must be served with javascript Content-Type."""
        js_files = [
            "api.js",
            "mock-api.js",
            "navigation.js",
            "voice.js",
            "finance.js",
            "documents.js",
            "settlement.js",
            "vehicle.js",
            "trips.js",
            "agent.js",
            "passenger.js",
            "app.js"
        ]
        for js_file in js_files:
            res = app_client.get(f"/js/{js_file}")
            assert res.status_code == 200, f"Failed to serve /js/{js_file}"
            content_type = res.headers.get("Content-Type", "")
            assert "javascript" in content_type or "text/plain" in content_type
            assert len(res.data) > 50

    def test_api_js_same_origin_configuration(self, app_client):
        """Verify api.js does not lock to http://localhost:5000 in production and defaults to live mode."""
        res = app_client.get("/js/api.js")
        assert res.status_code == 200
        js_code = res.get_data(as_text=True)
        assert "resolveApiBase" in js_code
        assert "resolveApiMode" in js_code
        # Verify default API_BASE is empty string / relative, not hardcoded localhost string
        assert 'API_BASE: "http://localhost:5000"' not in js_code
        # Verify default MODE is dynamic live mode resolution
        assert 'MODE: "mock"' not in js_code
        assert "return \"live\"" in js_code

    def test_serve_svg_assets(self, app_client):
        """SVG graphic assets must be served with 'image/svg+xml' Content-Type."""
        svg_assets = [
            "/assets/icons/auto-rickshaw.svg",
            "/assets/images/logo.svg"
        ]
        for svg_path in svg_assets:
            res = app_client.get(svg_path)
            assert res.status_code == 200, f"Failed to serve {svg_path}"
            assert "image/svg+xml" in res.headers.get("Content-Type", "")
            assert b"<svg" in res.data

    def test_spa_section_deep_links(self, app_client):
        """Known SPA section URLs must deliver index.html."""
        spa_sections = ["copilot", "trips", "finance", "documents", "settlement", "vehicle", "agent"]
        for section in spa_sections:
            res = app_client.get(f"/{section}")
            assert res.status_code == 200, f"Failed for section /{section}"
            assert "text/html" in res.headers.get("Content-Type", "")
            assert "T2T DRIVE" in res.get_data(as_text=True)

    def test_directory_traversal_blocked(self, app_client):
        """Path traversal attempts outside the frontend directory must return 404."""
        malicious_paths = [
            "/../backend/run.py",
            "/../../requirements.txt",
            "/css/../../backend/run.py",
            "/js/../app/config.py"
        ]
        for path in malicious_paths:
            res = app_client.get(path)
            assert res.status_code in (404, 400), f"Path {path} did not return 404/400"

    def test_nonexistent_static_file_returns_404(self, app_client):
        """Non-existent static files must return 404."""
        res = app_client.get("/css/nonexistent_file_98765.css")
        assert res.status_code == 404


class TestApiPreservation:
    """Verifies that all /api/* routes remain intact and are never intercepted by frontend."""

    def test_api_health_endpoint(self, app_client):
        """GET /api/health and /api/health/ must return 200 JSON status UP."""
        for path in ["/api/health", "/api/health/", "/health"]:
            res = app_client.get(path)
            assert res.status_code == 200, f"Health check failed for {path}"
            assert "application/json" in res.headers.get("Content-Type", "")
            data = res.get_json()
            assert data["success"] is True
            assert data["data"]["status"] == "UP"
            assert data["data"]["service"] == "T2T DRIVE Backend"

    def test_api_health_db_endpoint(self, app_client):
        """GET /api/health/db must return JSON database connectivity."""
        res = app_client.get("/api/health/db")
        assert res.status_code in (200, 503)
        assert "application/json" in res.headers.get("Content-Type", "")
        data = res.get_json()
        assert "database_connected" in (data.get("data") or data.get("details", {}))

    def test_nonexistent_api_route_returns_404_json(self, app_client):
        """Unknown /api/* paths must return structured 404 JSON, NOT HTML."""
        res = app_client.get("/api/nonexistent_endpoint_xyz_123")
        assert res.status_code == 404
        assert "application/json" in res.headers.get("Content-Type", "")
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "text/html" not in res.headers.get("Content-Type", "")


class TestFullWorkflowsViaFrontendDelivery:
    """Verifies complete end-to-end user journeys including auth, QR, passenger, and WSGI."""

    def test_driver_auth_and_dashboards(self, app_client):
        """Tests OTP authentication and dashboard API endpoints."""
        phone = "+919876599881"
        res_otp = app_client.post("/api/auth/request-otp", json={"phone": phone})
        assert res_otp.status_code == 200
        mock_otp = res_otp.get_json()["data"].get("_mock_otp", "123456")

        res_ver = app_client.post("/api/auth/verify-otp", json={"phone": phone, "otp": mock_otp})
        assert res_ver.status_code == 200
        token = res_ver.get_json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Verify finance dashboard summary
        res_fin = app_client.get("/api/finance/summary?period=today", headers=headers)
        assert res_fin.status_code == 200
        assert "metrics" in res_fin.get_json()["data"]

        # Verify documents vault
        res_docs = app_client.get("/api/documents", headers=headers)
        assert res_docs.status_code == 200
        assert "documents" in res_docs.get_json()["data"]

    def test_trip_creation_passenger_qr_and_passenger_access(self, app_client):
        """Verifies driver trip creation, passenger QR code, and passenger portal delivery."""
        phone = "+919876599882"
        res_otp = app_client.post("/api/auth/request-otp", json={"phone": phone})
        mock_otp = res_otp.get_json()["data"].get("_mock_otp", "123456")
        res_ver = app_client.post("/api/auth/verify-otp", json={"phone": phone, "otp": mock_otp})
        driver_token = res_ver.get_json()["data"]["token"]

        # Create Trip
        create_res = app_client.post(
            "/api/trips",
            json={
                "pickup_location": "T. Nagar Bus Terminus",
                "destination_location": "Chennai Central Railway Station",
                "fare": 180.00,
                "notes": "Luggage in rear rack"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert create_res.status_code == 201
        data = create_res.get_json()["data"]
        trip = data["trip"]
        raw_token = data["passenger_access_token"]
        passenger_url = data["passenger_url"]
        qr_code_svg = data["qr_code_svg"]

        assert "passenger.html" in passenger_url
        assert "token=" in passenger_url
        assert "<svg" in qr_code_svg

        # Fetch passenger URL directly through Flask frontend delivery
        from urllib.parse import urlparse
        parsed = urlparse(passenger_url)
        rel_path = f"{parsed.path}?{parsed.query}"

        pass_page_res = app_client.get(rel_path)
        assert pass_page_res.status_code == 200
        assert "Passenger Trip Co-Pilot" in pass_page_res.get_data(as_text=True)

        # Passenger API fetch
        pass_api_res = app_client.get(
            f"/api/passenger/trips/{trip['trip_id']}?token={raw_token}"
        )
        assert pass_api_res.status_code == 200
        assert pass_api_res.get_json()["data"]["trip"]["pickup_location"] == "T. Nagar Bus Terminus"

    def test_voice_chat_api_preserved(self, app_client):
        """Verifies voice conversation endpoint responds without regression."""
        import io
        phone = "+919876599883"
        res_otp = app_client.post("/api/auth/request-otp", json={"phone": phone})
        mock_otp = res_otp.get_json()["data"].get("_mock_otp", "123456")
        res_ver = app_client.post("/api/auth/verify-otp", json={"phone": phone, "otp": mock_otp})
        driver_token = res_ver.get_json()["data"]["token"]
        headers = {"Authorization": f"Bearer {driver_token}"}

        fake_wav = io.BytesIO(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
        res = app_client.post(
            "/api/voice/chat",
            headers=headers,
            data={
                "audio": (fake_wav, "input.wav"),
                "lang": "tanglish",
                "session_id": "test-sess-frontend",
                "generate_tts": "false"
            },
            content_type="multipart/form-data"
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True

    def test_exact_wsgi_gunicorn_target(self):
        """
        Validates the exact proposed Gunicorn WSGI target `run:app` and `wsgi:app`
        under a PEP 3333 compliant WSGI server invocation.
        """
        import sys
        from pathlib import Path
        import io

        backend_dir = str(Path(__file__).resolve().parent.parent.parent)
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        import run
        import wsgi
        assert callable(run.app), "run:app must be a callable WSGI application"
        assert callable(wsgi.app), "wsgi:app must be a callable WSGI application"
        assert run.application is run.app
        assert wsgi.application is wsgi.app

        wsgi_app = run.app

        status_received = []
        headers_received = []

        def start_response(status, response_headers, exc_info=None):
            status_received.append(status)
            headers_received.append(response_headers)
            return lambda x: None

        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/",
            "QUERY_STRING": "",
            "SERVER_NAME": "0.0.0.0",
            "SERVER_PORT": "10000",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(b""),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }

        body_chunks = wsgi_app(environ, start_response)
        body = b"".join(body_chunks)

        assert len(status_received) == 1
        assert status_received[0].startswith("200")
        assert b"T2T DRIVE" in body
        assert b"AI Voice Co-Pilot" in body


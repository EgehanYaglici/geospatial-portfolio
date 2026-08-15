"""Tests for Spatial API Lambda handler."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from handler import lambda_handler, json_response


class TestRouting:
    def test_health_route(self):
        event = {"httpMethod": "GET", "path": "/health"}
        with patch("handler.get_connection") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = ("3.4 USE_GEOS=1",)
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
            result = lambda_handler(event, None)
            assert result["statusCode"] == 200

    def test_not_found(self):
        event = {"httpMethod": "GET", "path": "/nonexistent"}
        result = lambda_handler(event, None)
        assert result["statusCode"] == 404

    def test_cors_preflight(self):
        event = {"httpMethod": "OPTIONS", "path": "/pois/nearby"}
        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        assert "Access-Control-Allow-Origin" in result["headers"]


class TestNearby:
    def test_missing_params(self):
        event = {"httpMethod": "GET", "path": "/pois/nearby", "queryStringParameters": {}}
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    def test_invalid_coordinates(self):
        event = {
            "httpMethod": "GET",
            "path": "/pois/nearby",
            "queryStringParameters": {"lon": "999", "lat": "52.37", "radius": "1000"},
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    def test_radius_capped(self):
        event = {
            "httpMethod": "GET",
            "path": "/pois/nearby",
            "queryStringParameters": {"lon": "4.89", "lat": "52.37", "radius": "99999"},
        }
        with patch("handler.get_connection") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = []
            mock_cur.description = []
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
            result = lambda_handler(event, None)
            # Should cap radius at 5000, not error
            assert result["statusCode"] == 200


class TestNearest:
    def test_missing_category(self):
        event = {
            "httpMethod": "GET",
            "path": "/facilities/nearest",
            "queryStringParameters": {"lon": "4.89", "lat": "52.37"},
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    def test_no_result(self):
        event = {
            "httpMethod": "GET",
            "path": "/facilities/nearest",
            "queryStringParameters": {"lon": "4.89", "lat": "52.37", "category": "hospital"},
        }
        with patch("handler.get_connection") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
            result = lambda_handler(event, None)
            assert result["statusCode"] == 404


class TestIntersects:
    def test_invalid_geometry(self):
        event = {
            "httpMethod": "POST",
            "path": "/analysis/intersects",
            "body": json.dumps({"geometry": {"type": "Point", "coordinates": [4, 52]}}),
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    def test_invalid_json(self):
        event = {"httpMethod": "POST", "path": "/analysis/intersects", "body": "not json"}
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    def test_complex_polygon_rejected(self):
        coords = [[i, i] for i in range(1001)]
        event = {
            "httpMethod": "POST",
            "path": "/analysis/intersects",
            "body": json.dumps({"geometry": {"type": "Polygon", "coordinates": [coords]}}),
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400


class TestJsonResponse:
    def test_format(self):
        resp = json_response(200, {"key": "value"})
        assert resp["statusCode"] == 200
        assert "Access-Control-Allow-Origin" in resp["headers"]
        body = json.loads(resp["body"])
        assert body["key"] == "value"

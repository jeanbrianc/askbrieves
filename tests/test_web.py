import base64
from unittest.mock import Mock

import pytest

from askbrieves import handler


@pytest.mark.parametrize("path,content_type", [("/", "text/html"), ("/app.js", "text/javascript"), ("/styles.css", "text/css")])
def test_public_web_assets_have_restrictive_headers_without_accessing_secrets(monkeypatch, path, content_type):
    secret = Mock(side_effect=AssertionError("Public assets must not fetch secrets"))
    monkeypatch.setattr(handler.storage, "secret", secret)
    result = handler.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": path}, None)
    assert result["statusCode"] == 200
    assert result["headers"]["content-type"].startswith(content_type)
    csp = result["headers"]["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert result["body"]
    secret.assert_not_called()


@pytest.mark.parametrize("path", ["/../storage.py", "/web/../storage.py", "/.env", "/app.js/../../storage.py"])
def test_web_assets_do_not_expose_arbitrary_files(path):
    result = handler.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": path}, None)
    assert result["statusCode"] == 404


def test_brand_image_is_a_valid_binary_png():
    result = handler.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/brand.png"}, None)
    assert result["statusCode"] == 200
    assert result["headers"]["content-type"] == "image/png"
    assert result["isBase64Encoded"] is True
    assert base64.b64decode(result["body"], validate=True).startswith(b"\x89PNG\r\n\x1a\n")

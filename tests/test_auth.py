from starlette.testclient import TestClient

from postfach_mcp.auth import BearerAuthMiddleware

TOKEN = "t" * 32
EXTRA = "e" * 32


async def inner_app(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": b"inner"})


def client() -> TestClient:
    return TestClient(BearerAuthMiddleware(inner_app, TOKEN))


def test_missing_header_rejected_with_www_authenticate():
    response = client().get("/anything")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_wrong_token_rejected():
    response = client().get("/x", headers={"Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 401


def test_wrong_scheme_rejected():
    response = client().get("/x", headers={"Authorization": "Basic " + TOKEN})
    assert response.status_code == 401


def test_correct_token_passes_through():
    response = client().get("/x", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.text == "inner"


def test_scheme_is_case_insensitive():
    response = client().get("/x", headers={"Authorization": f"bearer {TOKEN}"})
    assert response.status_code == 200


def test_health_path_exempt():
    response = client().get("/api/health")
    assert response.status_code == 200
    assert response.text == "inner"


def multi_client() -> TestClient:
    return TestClient(BearerAuthMiddleware(inner_app, (TOKEN, EXTRA)))


def test_every_configured_token_accepted():
    for token in (TOKEN, EXTRA):
        response = multi_client().get("/x", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


def test_unknown_token_rejected_with_multiple_configured():
    response = multi_client().get("/x", headers={"Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 401


def test_bare_string_treated_as_one_token_not_characters():
    response = client().get("/x", headers={"Authorization": "Bearer t"})
    assert response.status_code == 401

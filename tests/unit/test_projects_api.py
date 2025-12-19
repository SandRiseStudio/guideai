import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from guideai.projects_api import InMemoryProjectStore, create_project_routes


pytestmark = pytest.mark.unit


def _make_client() -> TestClient:
    app = FastAPI()
    store = InMemoryProjectStore()

    def get_user_id(_: Request) -> str:
        return "user-123"

    app.include_router(create_project_routes(store=store, get_user_id=get_user_id))
    return TestClient(app)


def test_create_personal_project_and_list() -> None:
    client = _make_client()

    resp = client.post(
        "/v1/projects",
        json={"name": "My Project", "description": "hello", "visibility": "private"},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"].startswith("proj-")
    assert created["name"] == "My Project"
    assert created["owner_id"] == "user-123"
    assert created["org_id"] is None

    list_resp = client.get("/v1/projects")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert "items" in payload
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == created["id"]


def test_create_project_with_org_id_still_single_resource_type() -> None:
    client = _make_client()

    resp = client.post("/v1/projects", json={"name": "Org Project", "org_id": "org-abc"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["org_id"] == "org-abc"
    assert created["owner_id"] == "user-123"

    # Filtering works
    list_resp = client.get("/v1/projects?org_id=org-abc")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == created["id"]

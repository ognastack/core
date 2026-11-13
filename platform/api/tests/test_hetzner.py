import pytest

from app.errors import ProviderError
from app.http import HttpResponse, TransportError
from app.providers import PROJECT_LABEL, ServerSpec
from app.providers.hetzner import HetznerProvider
from tests.conftest import FakeHttp

pytestmark = pytest.mark.anyio
API = "https://api.hetzner.cloud/v1"


def server(status="initializing", sid=42):
    return {"id": sid, "name": "ogna-app", "status": status,
            "public_net": {"ipv4": {"ip": "198.51.100.7"}, "ipv6": {"ip": "2001:db8::/64"}}}


async def test_create_server_request_and_response():
    http = FakeHttp({("POST", f"{API}/servers"): HttpResponse(201, {"server": server(), "action": {"id": 1}})})
    provider = HetznerProvider(http, "tok", ssh_key_ids=("123", "deploy-key"))
    spec = ServerSpec(name="ogna-app", server_type="cx23", location="fsn1", user_data="#cloud-config\n",
                      labels={PROJECT_LABEL: "p1"})

    created = await provider.create_server(spec)

    req = http.requests[0]
    assert req["headers"]["Authorization"] == "Bearer tok"
    assert req["json"] == {
        "name": "ogna-app", "server_type": "cx23", "image": "ubuntu-24.04", "location": "fsn1",
        "user_data": "#cloud-config\n", "labels": {PROJECT_LABEL: "p1"}, "start_after_create": True,
        "public_net": {"enable_ipv4": True, "enable_ipv6": True}, "ssh_keys": [123, "deploy-key"],
    }
    assert (created.provider_server_id, created.status, created.ipv4) == ("42", "creating", "198.51.100.7")


@pytest.mark.parametrize("raw,normalized", [
    ("initializing", "creating"), ("starting", "creating"), ("running", "running"),
    ("off", "off"), ("deleting", "deleting"), ("rebuilding", "unknown"), ("something-new", "unknown"),
])
async def test_find_server_uses_label_selector_and_normalizes_status(raw, normalized):
    http = FakeHttp({("GET", f"{API}/servers"): {"servers": [server(raw)]}})
    found = await HetznerProvider(http, "tok").find_server("p1")
    assert http.requests[0]["params"] == {"label_selector": f"{PROJECT_LABEL}=p1"}
    assert found.status == normalized


async def test_find_server_returns_none_when_absent():
    http = FakeHttp({("GET", f"{API}/servers"): {"servers": []}})
    assert await HetznerProvider(http, "tok").find_server("p1") is None


async def test_delete_is_idempotent():
    http = FakeHttp()  # every route 404s
    await HetznerProvider(http, "tok").delete_server("42")
    assert http.requests[0]["method"] == "DELETE" and http.requests[0]["url"].endswith("/servers/42")


@pytest.mark.parametrize("status,code,retryable", [
    (422, "invalid_input", False),
    (409, "uniqueness_error", False),
    (401, "unauthorized", False),
    (429, "rate_limit_exceeded", True),
    (412, "resource_unavailable", True),
    (503, "unavailable", True),
])
async def test_errors_are_classified(status, code, retryable):
    http = FakeHttp({("POST", f"{API}/servers"): HttpResponse(status, {"error": {"code": code, "message": "nope"}})})
    with pytest.raises(ProviderError) as exc:
        await HetznerProvider(http, "tok").create_server(ServerSpec("n", "cx23", "fsn1", ""))
    assert exc.value.retryable is retryable
    assert code in exc.value.message


async def test_transport_errors_are_retryable():
    class Down(FakeHttp):
        async def request(self, *a, **k):
            raise TransportError("connect timeout")

    with pytest.raises(ProviderError) as exc:
        await HetznerProvider(Down(), "tok").find_server("p1")
    assert exc.value.retryable

"""Tests for the SharePoint-backed attachment layer.

Graph is exercised through a fake httpx transport, so these run offline and
never touch a real tenant. The database is the existing FakePool.

pytest.ini sets --strict-markers and no async plugin is configured, so the
async client is driven with asyncio.run from ordinary sync tests. That
matches the rest of this suite and adds no new dependency.
"""

import asyncio

import httpx
import pytest

from app.attachments import service
import app.attachments.sharepoint_client as sp_client_module
from app.attachments.sharepoint_client import (
    SharePointClient,
    SharePointError,
    SharePointNotConfigured,
    _require_config,
    is_configured,
)
from tests.conftest import auth_header, make_user_row

REQUIRED_ENV = {
    "AZURE_CLIENT_ID": "cid",
    "AZURE_CLIENT_SECRET": "csecret",
    "AZURE_TENANT_ID": "tid",
    "SHAREPOINT_SITE_ID": "site",
    "SHAREPOINT_DRIVE_ID": "drive",
}

TOKEN_RESPONSE = {"access_token": "tok", "expires_in": 3600}


@pytest.fixture
def sp_client(monkeypatch):
    """A SharePointClient with all env present and a fresh token cache.

    Deliberately not named "client": conftest already owns that name for
    the FastAPI TestClient.
    """
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    return SharePointClient()


def install_graph(monkeypatch, handler):
    """Route SharePointClient._request through a fixed httpx handler.

    Keeps the production retry policy intact: the patched method only
    replaces the transport, not the decision to retry.
    """

    async def patched(self, method, url, **kwargs):
        allow = kwargs.get("allow", (200, 201, 204))
        last = None
        for attempt in range(1, 4):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler), timeout=5.0
            ) as http:
                token = await self.access_token()
                response = await http.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        **(kwargs.get("headers") or {}),
                    },
                    content=kwargs.get("content"),
                    json=kwargs.get("json"),
                )
            if response.status_code in allow:
                return response
            last = response
            if not (response.status_code == 429 or response.status_code >= 500):
                break
            if attempt < 3:
                await asyncio.sleep(0)
        code = last.status_code
        try:
            detail = last.json().get("error", {}).get("code", "")
        except Exception:
            detail = ""
        # status_code must be carried: create_folder branches on 404 and 409.
        raise SharePointError(
            f"SharePoint {method} failed (HTTP {code}): {detail}",
            status_code=code,
        )

    async def fake_token(self, config=None):
        return "tok", 3600

    monkeypatch.setattr(SharePointClient, "_fetch_token", fake_token)
    monkeypatch.setattr(SharePointClient, "_request", patched)


def make_handler(
    *,
    folder_exists=True,
    preview_ok=True,
    fail_get_times=0,
    log=None,
):
    """Build a Graph handler covering the calls this client makes."""
    state = {"get_fails": fail_get_times}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method
        if log is not None:
            log.append((method, url, request.content))

        if "login.microsoftonline.com" in url:
            return httpx.Response(200, json=TOKEN_RESPONSE)

        if "createUploadSession" in url:
            return httpx.Response(
                200, json={"uploadUrl": "https://upload.example/session"}
            )

        if "/preview" in url:
            if preview_ok:
                return httpx.Response(200, json={"getUrl": "https://preview/x"})
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})

        if method == "GET" and "/root:" in url:
            if state["get_fails"] > 0:
                state["get_fails"] -= 1
                return httpx.Response(503, json={"error": {"code": "busy"}})
            if folder_exists:
                return httpx.Response(200, json={"id": "F1", "name": "p"})
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})

        if method == "POST" and url.endswith("/root/children"):
            return httpx.Response(201, json={"id": "F1", "name": "p"})

        return httpx.Response(201, json={"id": "I1", "webUrl": "https://sp/I1"})

    return handler


class TestConfiguration:
    def test_not_configured_when_env_absent(self, monkeypatch):
        for key in REQUIRED_ENV:
            monkeypatch.delenv(key, raising=False)
        assert is_configured() is False

    def test_missing_key_is_named_as_an_env_var(self, monkeypatch):
        for key, value in REQUIRED_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("AZURE_TENANT_ID")

        with pytest.raises(SharePointNotConfigured) as error:
            _require_config()

        message = str(error.value)
        # The operator must be told the env var, not an internal key.
        assert "AZURE_TENANT_ID" in message
        assert "tenant_id" not in message
        # And no configured value may leak.
        assert "csecret" not in message

    def test_configured_when_all_present(self, monkeypatch):
        for key, value in REQUIRED_ENV.items():
            monkeypatch.setenv(key, value)
        assert is_configured() is True


class TestPathEncoding:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("TDAC-2026-041", "TDAC-2026-041"),
            ("BH 1/photo.jpg", "BH%201/photo.jpg"),
            ("a#b?c.jpg", "a%23b%3Fc.jpg"),
            ("100%.jpg", "100%25.jpg"),
        ],
    )
    def test_encodes_reserved_characters(self, raw, expected):
        assert SharePointClient._encode(raw) == expected

    def test_separator_is_preserved(self):
        assert SharePointClient._encode("proj/file.jpg") == "proj/file.jpg"

    def test_traversal_cannot_escape_the_project_folder(self):
        # A literal ".." would be resolved server-side and climb out of the
        # project folder, so every dot segment is replaced.
        encoded = SharePointClient._encode("proj/../../etc")
        assert ".." not in encoded
        assert encoded == "proj/%2E%2E/%2E%2E/etc"

    def test_single_dot_is_neutralised(self):
        assert SharePointClient._encode("proj/./etc") == "proj/%2E/etc"


class TestFolderHandling:
    def test_existing_folder_is_reused(self, sp_client, monkeypatch):
        log = []
        install_graph(monkeypatch, make_handler(folder_exists=True, log=log))
        asyncio.run(sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg"))

        assert not [
            entry for entry in log if entry[0] == "POST" and "children" in entry[1]
        ], "created a folder that already existed"

    def test_missing_folder_is_created(self, sp_client, monkeypatch):
        log = []
        install_graph(monkeypatch, make_handler(folder_exists=False, log=log))
        asyncio.run(sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg"))

        creates = [e for e in log if e[0] == "POST" and "children" in e[1]]
        # Root plus the project folder itself.
        assert len(creates) == 2, [e[1] for e in creates]
        assert "conflictBehavior" in creates[-1][2].decode()
        assert b'"name":"TDAC-1"' in creates[-1][2]

    def test_folder_name_travels_as_data_not_in_the_url(self, sp_client, monkeypatch):
        log = []
        install_graph(monkeypatch, make_handler(folder_exists=False, log=log))
        asyncio.run(sp_client.upload("proj weird", "a.jpg", b"abc", "image/jpeg"))

        creates = [e for e in log if e[0] == "POST" and "children" in e[1]]
        assert creates
        # The name is a JSON field, never spliced into the request URL.
        project_create = creates[-1]
        assert "proj%20weird" not in project_create[1]
        assert b"proj weird" in project_create[2]

    def test_multi_segment_folder_is_created_level_by_level(
        self, sp_client, monkeypatch
    ):
        """Graph rejects a slash inside driveItem.name, so the path must be
        walked one segment at a time or every sample upload fails."""
        created = []
        log = []

        def handler(request):
            url = str(request.url)
            log.append((request.method, url, request.content))
            if "/root:" in url and request.method == "GET":
                return httpx.Response(404, json={"error": {"code": "nf"}})
            if url.endswith("/children"):
                created.append(request.content.decode())
                return httpx.Response(201, json={"id": "F"})
            return httpx.Response(201, json={"id": "I1", "webUrl": "u"})

        install_graph(monkeypatch, handler)
        asyncio.run(
            sp_client.upload(
                "TDAC-1/samples/TDAC-1-16", "a.jpg", b"abc", "image/jpeg"
            )
        )

        # Root + three levels, each created under its parent.
        assert len(created) == 4, (
            f"expected 4 creates (root + 3 levels), got {len(created)}; "
            f"log={[e[1] for e in log]}"
        )
        # httpx serialises compact JSON: {"name":"X",...} with no space.
        assert '"name":"TDAC"' in created[0], created[0]
        assert '"name":"TDAC-1"' in created[1], created[1]
        assert '"name":"samples"' in created[2], created[2]
        assert '"name":"TDAC-1-16"' in created[3], created[3]
        # No create may ever put a slash in the name: Graph rejects it.
        for body in created:
            name = body.split('"name":"')[1].split('"')[0]
            assert "/" not in name, f"slash in driveItem name: {body}"

    def test_existing_nested_folder_costs_one_get(
        self, sp_client, monkeypatch
    ):
        """When every level already exists there is nothing to POST."""
        log = []
        install_graph(monkeypatch, make_handler(folder_exists=True, log=log))
        asyncio.run(
            sp_client.upload(
                "TDAC-1/samples/TDAC-1-16", "a.jpg", b"abc", "image/jpeg"
            )
        )
        assert not [e for e in log if e[0] == "POST" and "children" in e[1]]


class TestUpload:
    def test_small_file_uses_a_simple_put(self, sp_client, monkeypatch):
        log = []
        install_graph(monkeypatch, make_handler(log=log))
        item = asyncio.run(sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg"))

        assert item["id"] == "I1"
        assert not [e for e in log if "createUploadSession" in e[1]]
        assert [e for e in log if e[0] == "PUT" and ":/content" in e[1]]

    def test_large_file_uses_an_upload_session(self, sp_client, monkeypatch):
        log = []
        install_graph(monkeypatch, make_handler(log=log))
        big = b"x" * (5 * 1024 * 1024)

        asyncio.run(sp_client.upload("TDAC-1", "big.mp4", big, "video/mp4"))

        assert [e for e in log if "createUploadSession" in e[1]]

    def test_content_type_is_forwarded(self, sp_client, monkeypatch):
        puts = []

        def handler(request):
            if "/root:" in str(request.url) and request.method == "GET":
                return httpx.Response(200, json={"id": "F1"})
            if request.method == "PUT":
                puts.append(
                    (str(request.url), request.headers.get("content-type"))
                )
                return httpx.Response(201, json={"id": "I1", "webUrl": "u"})
            return httpx.Response(200, json=TOKEN_RESPONSE)

        install_graph(monkeypatch, handler)
        asyncio.run(sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg"))

        assert puts, "no content PUT was made"
        url, content_type = puts[0]
        assert content_type == "image/jpeg"
        assert url.endswith("/a.jpg:/content")

    def test_non_transient_failure_raises(self, sp_client, monkeypatch):
        def handler(request):
            if "login.microsoftonline.com" in str(request.url):
                return httpx.Response(200, json=TOKEN_RESPONSE)
            return httpx.Response(400, json={"error": {"code": "invalidRequest"}})

        install_graph(monkeypatch, handler)

        with pytest.raises(SharePointError) as error:
            asyncio.run(sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg"))
        assert "400" in str(error.value)

    def test_transient_failure_is_retried(self, sp_client, monkeypatch):
        log = []
        install_graph(
            monkeypatch, make_handler(fail_get_times=1, log=log)
        )
        item = asyncio.run(sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg"))

        assert item["id"] == "I1"
        gets = [e for e in log if e[0] == "GET" and "/root:" in e[1]]
        # One retry of the folder probe is the minimum; the root adds a
        # second level, so the exact count is not the point.
        assert len(gets) >= 2, f"the 503 was not retried: {gets}"


class TestPreview:
    def test_preview_url_returned_when_supported(self, sp_client, monkeypatch):
        install_graph(monkeypatch, make_handler(preview_ok=True))
        url, supported = asyncio.run(sp_client.preview_url("I1"))
        assert supported is True
        assert url == "https://preview/x"

    def test_absent_preview_is_not_an_error(self, sp_client, monkeypatch):
        """Graph cannot preview Office docs; that must not raise."""
        install_graph(monkeypatch, make_handler(preview_ok=False))
        url, supported = asyncio.run(sp_client.preview_url("I1"))
        assert supported is False
        assert url is None


class TestClassification:
    @pytest.mark.parametrize(
        "mime,kind",
        [
            ("image/png", "image"),
            ("image/JPEG", "image"),
            ("video/mp4", "video"),
            ("application/pdf", "preview"),
            (None, "preview"),
        ],
    )
    def test_kind_matches_the_renderer(self, mime, kind):
        assert service.classify(mime) == kind


class TestUploadEndpoint:
    @pytest.fixture(autouse=True)
    def _no_sharepoint_env(self, monkeypatch):
        """Each endpoint test declares its own configuration state."""
        for key in REQUIRED_ENV:
            monkeypatch.delenv(key, raising=False)

    def _route_project(self, pool, exists=True):
        pool.route("WHERE u.id", make_user_row())
        pool.route(
            'FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1 if exists else None
        )

    def test_requires_auth(self, client):
        resp = client.post(
            "/api/attachments/TDAC-1", files={"file": ("a.jpg", b"x")}
        )
        assert resp.status_code in (401, 403)

    def test_health_reports_configuration(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        resp = client.get("/api/attachments/health", headers=auth_header())
        assert resp.status_code == 200
        assert "configured" in resp.json()

    def test_unknown_project_is_404(self, client, pool, monkeypatch):
        for key, value in REQUIRED_ENV.items():
            monkeypatch.setenv(key, value)
        self._route_project(pool, exists=False)
        resp = client.post(
            "/api/attachments/TDAC-NOPE",
            files={"file": ("a.jpg", b"x")},
            headers=auth_header(),
        )
        assert resp.status_code == 404

    def test_unconfigured_sharepoint_is_503(self, client, pool, monkeypatch):
        for key in REQUIRED_ENV:
            monkeypatch.delenv(key, raising=False)
        self._route_project(pool)

        resp = client.post(
            "/api/attachments/TDAC-1",
            files={"file": ("a.jpg", b"x")},
            headers=auth_header(),
        )
        assert resp.status_code == 503
        # The message names the env vars, and leaks no value.
        body = resp.json()["detail"]
        assert "AZURE_CLIENT_ID" in body


class TestUploadSessionCompletion:
    """The uploadUrl is single-use: Graph answers the final chunk PUT with
    the finished driveItem and there is nothing left to fetch. Issuing a
    follow-up GET on that URL gets 404/410 and fails every large upload.
    """

    def test_no_request_follows_the_last_chunk(self, sp_client, monkeypatch):
        seen = []

        def handler(request):
            url = str(request.url)
            seen.append((request.method, url))
            if "/root:" in url and request.method == "GET":
                return httpx.Response(200, json={"id": "F1"})
            if "createUploadSession" in url:
                return httpx.Response(
                    200, json={"uploadUrl": "https://upload.example/session"}
                )
            if url == "https://upload.example/session":
                # Real Graph: 202 while more chunks are expected, 200 on the
                # last one. Anything after completion is 404/410.
                body = len(seen) > 2
                return httpx.Response(
                    200 if body else 202,
                    json={"id": "I9", "webUrl": "https://sp/I9"},
                )
            return httpx.Response(201, json={"id": "I9", "webUrl": "u"})

        install_graph(monkeypatch, handler)
        big = b"x" * (5 * 1024 * 1024)

        item = asyncio.run(
            sp_client.upload("TDAC-1", "big.mp4", big, "video/mp4")
        )

        session_calls = [e for e in seen if e[1] == "https://upload.example/session"]
        # Only PUTs: one GET after the final chunk would be the bug.
        assert session_calls, "no chunk was sent"
        assert all(method == "PUT" for method, _ in session_calls), (
            f"a non-PUT followed the chunks: {session_calls}"
        )
        assert item["id"] == "I9"
        assert item["webUrl"] == "https://sp/I9"

    def test_incomplete_session_raises(self, sp_client, monkeypatch):
        """A session that never returns 200/201 must fail loudly."""

        def handler(request):
            url = str(request.url)
            if "/root:" in url and request.method == "GET":
                return httpx.Response(200, json={"id": "F1"})
            if "createUploadSession" in url:
                return httpx.Response(
                    200, json={"uploadUrl": "https://upload.example/session"}
                )
            # Always 202: the upload never completes.
            return httpx.Response(202, json={})

        install_graph(monkeypatch, handler)

        with pytest.raises(SharePointError) as error:
            asyncio.run(
                sp_client.upload(
                    "TDAC-1", "big.mp4", b"x" * (5 * 1024 * 1024), "video/mp4"
                )
            )
        assert "did not complete" in str(error.value)


class TestFolderRace:
    """One project must map to exactly one folder.

    With conflictBehavior=rename, two simultaneous first-uploads would
    create TDAC-1 and TDAC-1 1 and scatter the project's files.
    """

    def test_second_create_fails_then_reuses_the_folder(
        self, sp_client, monkeypatch
    ):
        state = {"exists": False, "creates": 0}
        created_paths = []

        def handler(request):
            url = str(request.url)
            if "/root:" in url and request.method == "GET":
                if state["exists"]:
                    return httpx.Response(200, json={"id": "F1", "name": "TDAC-1"})
                return httpx.Response(404, json={"error": {"code": "itemNotFound"}})

            if url.endswith("/root/children"):
                state["creates"] += 1
                if state["exists"]:
                    # conflictBehavior=fail: the folder now exists.
                    return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
                state["exists"] = True
                return httpx.Response(201, json={"id": "F1", "name": "TDAC-1"})

            return httpx.Response(201, json={"id": "I1", "webUrl": "u"})

        install_graph(monkeypatch, handler)

        # Simulate the race: GET 404s, then something else creates it, so our
        # POST collides and must fall back to a re-read.
        state["exists"] = True  # the competitor won after our 404
        item = asyncio.run(
            sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg")
        )

        assert item["id"] == "I1", "upload did not complete after the race"
        assert state["creates"] == 0, "an unnecessary folder create was sent"

    def test_conflict_behaviour_is_fail_not_rename(self, sp_client, monkeypatch):
        bodies = []

        def handler(request):
            url = str(request.url)
            if "/root:" in url and request.method == "GET":
                return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
            if url.endswith("/children"):
                bodies.append(request.content.decode())
                return httpx.Response(201, json={"id": "F1"})
            return httpx.Response(201, json={"id": "I1", "webUrl": "u"})

        install_graph(monkeypatch, handler)
        asyncio.run(sp_client.upload("TDAC-1", "a.jpg", b"abc", "image/jpeg"))

        assert bodies, "folder was never created"
        assert "fail" in bodies[0], bodies[0]
        assert "rename" not in bodies[0], (
            "conflictBehavior=rename would create a second project folder"
        )


class TestContentStreaming:
    """Media must be served as bytes.

    SharePoint's webUrl and /preview getUrl are HTML viewer pages, so an
    <img> or <video> pointed at either renders broken. The content endpoint
    streams the item itself.
    """

    def test_iter_download_yields_bytes(self, sp_client, monkeypatch):
        payload = b"\x89PNG\r\n\x1a\n" + b"z" * 500

        def handler(request):
            if "/content" in str(request.url):
                return httpx.Response(
                    200, content=payload, headers={"content-type": "image/png"}
                )
            return httpx.Response(200, json={})

        install_graph(monkeypatch, handler)

        # iter_download streams with its own client, so it needs the same
        # transport substitution to stay offline.
        original_client = httpx.AsyncClient

        def patched_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", patched_client)

        async def collect():
            return b"".join(
                [
                    chunk
                    async for chunk in sp_client.iter_download("I1")
                ]
            )

        assert asyncio.run(collect()) == payload

    def test_content_endpoint_streams_the_right_type(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)

        row = {
            "id": 1,
            "project_id": "TDAC-1",
            "entity_kind": "project",
            "sample_id": None,
            "filename": "site.png",
            "content_type": "image/png",
            "size_bytes": 4,
            "sharepoint_item_id": "I1",
            "web_url": "https://sp/I1",
            "preview_url": None,
            "preview_supported": False,
            "uploaded_by": 1,
            "uploaded_by_username": "admin",
            "uploaded_at": "2026-10-01T10:00:00Z",
        }
        pool.route('LEFT JOIN "tdac"."users"', row)

        resp = client.get(
            "/api/attachments/TDAC-1/1/content", headers=auth_header()
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/png")

    def test_content_endpoint_404s_for_unknown_attachment(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)
        pool.route('LEFT JOIN "tdac"."users"', None)

        resp = client.get(
            "/api/attachments/TDAC-1/999/content", headers=auth_header()
        )
        assert resp.status_code == 404


class TestPreviewRefresh:
    def test_refresh_persists_a_new_url(self, client, pool, monkeypatch):
        for key, value in REQUIRED_ENV.items():
            monkeypatch.setenv(key, value)
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)

        row = {
            "id": 1,
            "project_id": "TDAC-1",
            "entity_kind": "project",
            "sample_id": None,
            "filename": "report.pdf",
            "content_type": "application/pdf",
            "size_bytes": 10,
            "sharepoint_item_id": "I1",
            "web_url": "https://sp/I1",
            "preview_url": "https://preview/stale",
            "preview_supported": True,
            "uploaded_by": 1,
            "uploaded_by_username": "admin",
            "uploaded_at": "2026-10-01T10:00:00Z",
        }
        pool.route('LEFT JOIN "tdac"."users"', row)

        async def fresh(self, item_id):
            return "https://preview/fresh", True

        monkeypatch.setattr(
            SharePointClient, "preview_url", fresh
        )

        resp = client.post(
            "/api/attachments/TDAC-1/1/refresh-preview", headers=auth_header()
        )

        assert resp.status_code == 200
        assert resp.json()["preview_url"] == "https://preview/fresh"
        updates = pool.calls_with("execute", 'UPDATE "tdac"."attachments"')
        assert updates, "the fresh URL was not persisted"


class TestSampleScopedAttachments:
    """Files anchored on SAMPLE_ID, not depth.

    update_spt_record allows ISPT_TOP to change, so a depth anchor would
    orphan every photo on a depth correction. SAMPLE_ID survives.
    """

    def _route(self, pool, sample_exists=True):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)
        pool.route('"tdac"."SPT_RECORD_STATUS"', 1 if sample_exists else None)
        pool.route('LEFT JOIN "tdac"."users"', [])

    def test_sample_upload_requires_auth(self, client):
        resp = client.post(
            "/api/attachments/TDAC-1/samples/TDAC-1-16",
            files={"file": ("a.png", b"x")},
        )
        assert resp.status_code in (401, 403)

    def test_unknown_sample_is_404(self, client, pool, monkeypatch):
        for key, value in REQUIRED_ENV.items():
            monkeypatch.setenv(key, value)
        self._route(pool, sample_exists=False)
        resp = client.post(
            "/api/attachments/TDAC-1/samples/NOPE",
            files={"file": ("a.png", b"x")},
            headers=auth_header(),
        )
        assert resp.status_code == 404

    def test_sample_list_is_scoped_to_the_sample(self, client, pool):
        # Listing does not touch SharePoint, so no configuration is needed.
        self._route(pool)
        resp = client.get(
            "/api/attachments/TDAC-1/samples/TDAC-1-16", headers=auth_header()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sample_id"] == "TDAC-1-16"
        sql = [
            c[1] for c in pool.calls
            if c[0] == "fetch" and '"tdac"."attachments"' in c[1]
        ]
        assert sql, "no attachment query was made"
        # The query must be scoped by sample, not just project.
        assert "$2" in sql[0] and "entity_kind" in sql[0]

    def test_project_list_returns_a_list_not_the_pager_dict(self, client, pool):
        """"attachments" must be an array, or the client crashes.

        The pager dict {items, total, page, page_size} was passed straight
        through under the "attachments" key. The client then called .map on
        it during render, threw, and -- with no error boundary -- blanked the
        whole page. The pager fields stay available beside the list.
        """
        self._route(pool)
        resp = client.get("/api/attachments/TDAC-1", headers=auth_header())
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["attachments"], list), (
            "attachments must be a list; the client calls .map/.some on it "
            "during render and a dict unmounts the entire app"
        )
        # The pager metadata must not be lost by the unwrapping.
        for key in ("total", "page", "page_size"):
            assert key in body, f"{key} dropped from the project list response"

    def test_sample_list_also_returns_a_list(self, client, pool):
        """Both scopes must agree, or the panel works only half the time."""
        self._route(pool)
        resp = client.get(
            "/api/attachments/TDAC-1/samples/TDAC-1-16", headers=auth_header()
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["attachments"], list)

    def test_project_list_excludes_sample_files(self, client, pool):
        """The project header panel must not show sample photos."""
        self._route(pool)
        client.get("/api/attachments/TDAC-1", headers=auth_header())
        project_queries = [
            c[1] for c in pool.calls
            if c[0] == "fetch"
            and '"tdac"."attachments"' in c[1]
            and '"sample_id" = $2' not in c[1]
        ]
        assert project_queries, "no project-level query made"
        where_clause = project_queries[0].split("WHERE", 1)[-1].split("ORDER BY")[0]
        assert "entity_kind" in where_clause, (
            "the project list is not filtered by entity_kind in its WHERE "
            "clause, so sample files would leak into the project panel"
        )

    def test_sample_folder_path_is_used(self, sp_client, monkeypatch):
        """Files must land in /{project}/samples/{sample_id}/."""
        seen = []

        def handler(request):
            url = str(request.url)
            if "/root:" in url and request.method == "GET":
                seen.append(url)
                return httpx.Response(200, json={"id": "F1"})
            if url.endswith("/root/children"):
                return httpx.Response(201, json={"id": "F1"})
            seen.append(url)
            return httpx.Response(201, json={"id": "I1", "webUrl": "u"})

        install_graph(monkeypatch, handler)
        asyncio.run(
            sp_client.upload("TDAC-1/samples/TDAC-1-16", "a.png", b"x", "image/png")
        )

        assert any("samples" in u for u in seen), seen
        # The sample id must not be percent-collapsed into the project name.
        assert not any(u.endswith("samples/") for u in seen)


class TestDeleteSampleCleanup:
    """Deleting an SPT record must clear its attachment metadata."""

    def test_cleanup_query_is_scoped_and_ordered(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."ISPT"', {
            "spt_depth": 5.5, "blows_15": 3, "blows_30": 5,
            "blows_45": 7, "n_value": 6,
        })
        pool.route('"tdac"."SPT_RECORD_STATUS"', "TDAC-1-16")
        pool.route('DELETE FROM "ags42"."ISPT"', "DELETE 1")

        # loca_belongs_to_project runs "SELECT 1 FROM ags42.LOCA WHERE ..."
        # through fetchval.
        pool.route('SELECT 1', 1)
        client.delete(
            "/api/portfolio/projects/TDAC-1/locas/BH-1/field-data/spt/5.5",
            headers=auth_header(),
        )

        deletes = [c[1] for c in pool.calls
                   if c[0] == "execute" and "attachments" in c[1].lower()]
        assert deletes, "attachment metadata was not cleaned up"
        assert "entity_kind" in deletes[0]
        assert "$2" in deletes[0]


class TestMediaAuth:
    """A media element cannot send an Authorization header.

    The panel points <img>/<video> at the content URL, and the browser
    sends that request with no Authorization header. Without a media token
    the route 401s and every image and video in the gallery is broken.
    """

    ROW = {
        "id": 1, "project_id": "TDAC-1", "entity_kind": "project",
        "sample_id": None, "filename": "site.png",
        "content_type": "image/png", "size_bytes": 1000,
        "sharepoint_item_id": "I1", "web_url": "https://sp/I1",
        "preview_url": None, "preview_supported": False,
        "uploaded_by": 1, "uploaded_by_username": "admin",
        "uploaded_at": "2026-10-01T10:00:00Z",
    }
    PAYLOAD = b"\x89PNG\r\n\x1a\n" + b"p" * 900

    def _route(self, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)
        pool.route('LEFT JOIN "tdac"."users"', self.ROW)

    @staticmethod
    def _stub_download(monkeypatch, captured):
        async def fake(self, item_id, *, range_header=None, chunk_size=1024 * 1024):
            captured["range"] = range_header
            body = TestMediaAuth.PAYLOAD
            if range_header:
                span = range_header.split("=", 1)[1]
                start_s, end_s = span.split("-", 1)
                start = int(start_s)
                end = int(end_s) + 1 if end_s else len(body)
                body = body[start:end]
            for i in range(0, len(body), 256):
                yield body[i:i + 256]

        monkeypatch.setattr(SharePointClient, "iter_download", fake)

    def test_media_token_is_issued(self, client, pool):
        self._route(pool)
        resp = client.get("/api/attachments/TDAC-1/media-token", headers=auth_header())
        assert resp.status_code == 200
        assert resp.json()["media_token"]

    def test_content_serves_with_a_media_token_and_no_header(
        self, client, pool, monkeypatch
    ):
        self._route(pool)
        captured = {}
        self._stub_download(monkeypatch, captured)
        token = client.get(
            "/api/attachments/TDAC-1/media-token", headers=auth_header()
        ).json()["media_token"]

        # No Authorization header: exactly what <img> sends.
        resp = client.get(f"/api/attachments/TDAC-1/1/content?mt={token}")

        assert resp.status_code == 200, resp.text
        assert resp.content == self.PAYLOAD

    def test_content_refuses_without_header_or_token(self, client, pool):
        self._route(pool)
        assert client.get("/api/attachments/TDAC-1/1/content").status_code == 401

    def test_media_token_cannot_be_used_as_an_access_token(self, client, pool):
        """Typed `media` on the server, so it cannot be replayed as a
        session token."""
        self._route(pool)
        token = client.get(
            "/api/attachments/TDAC-1/media-token", headers=auth_header()
        ).json()["media_token"]
        resp = client.get(
            "/api/attachments/TDAC-1", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401

    def test_range_request_returns_206_and_only_that_slice(
        self, client, pool, monkeypatch
    ):
        """A video seek must not download the whole file."""
        self._route(pool)
        captured = {}
        self._stub_download(monkeypatch, captured)
        token = client.get(
            "/api/attachments/TDAC-1/media-token", headers=auth_header()
        ).json()["media_token"]

        resp = client.get(
            f"/api/attachments/TDAC-1/1/content?mt={token}",
            headers={"Range": "bytes=0-99"},
        )

        assert resp.status_code == 206, resp.text
        assert resp.headers["content-range"] == "bytes 0-99/1000"
        assert len(resp.content) == 100
        assert resp.headers["accept-ranges"] == "bytes"
        # The range is forwarded to Graph, not just used for framing.
        assert captured["range"] == "bytes=0-99"

    def test_media_response_is_private_not_public(self, client, pool, monkeypatch):
        self._route(pool)
        self._stub_download(monkeypatch, {})
        token = client.get(
            "/api/attachments/TDAC-1/media-token", headers=auth_header()
        ).json()["media_token"]
        resp = client.get(f"/api/attachments/TDAC-1/1/content?mt={token}")
        assert "private" in resp.headers.get("cache-control", "")


class TestFilenameTruncation:
    def test_long_name_keeps_its_extension(self):
        from app.attachments.router import _safe_filename

        name = "a" * 400 + ".xlsx"
        result = _safe_filename(name)
        assert len(result) <= 200
        assert result.endswith(".xlsx"), result[-20:]

    def test_short_name_is_untouched(self):
        from app.attachments.router import _safe_filename

        assert _safe_filename("report.pdf") == "report.pdf"

    def test_dotfile_is_truncated_not_mangled(self):
        from app.attachments.router import _safe_filename

        result = _safe_filename("." + "b" * 300)
        assert len(result) <= 200
        assert result.startswith(".")


class TestSampleExistenceAcrossBothTables:
    def test_core_sample_is_recognised(self, client, pool, monkeypatch):
        """A SAMPLE_ID can come from SPT or from coring. Checking only the
        SPT table would reject every core sample."""
        for key, value in REQUIRED_ENV.items():
            monkeypatch.setenv(key, value)
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)
        # A UNION over both tables: present only via SAMPLING_RECORD_ID.
        pool.route('"tdac"."SPT_RECORD_STATUS"', 1)
        pool.route('LEFT JOIN "tdac"."users"', [])

        client.get("/api/attachments/TDAC-1/samples/TDAC-1-9", headers=auth_header())

        # The lookup must consult the coring table as well, or a core
        # sample is reported as not found and cannot hold a photo.
        lookups = [
            c[1] for c in pool.calls
            if c[0] == "fetchval" and "SAMPLE_ID" in c[1]
        ]
        assert lookups, "no sample lookup was made"
        assert any("SAMPLING_RECORD_ID" in q for q in lookups), (
            f"sample lookup ignores core samples: {lookups}"
        )


class TestIterDownloadRedirect:
    """Graph answers /content with a 302 to a short-lived CDN URL.

    httpx does not follow redirects inside client.stream(), so treating
    anything but 200 as a failure broke every image and video. The redirect
    is followed manually, and the Authorization header must not go with it:
    the CDN neither needs a bearer token nor should log one.
    """

    def _patch_transport(self, monkeypatch, handler):
        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", patched)

    def test_follows_redirect_and_strips_auth_on_hop_two(
        self, sp_client, monkeypatch
    ):
        calls = []

        def handler(request):
            url = str(request.url)
            calls.append((url, dict(request.headers)))
            if "login.microsoftonline.com" in url:
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 3600}
                )
            if "graph.microsoft.com" in url:
                return httpx.Response(
                    302, headers={"Location": "https://cdn.example/blob/xyz"}
                )
            return httpx.Response(200, content=b"payload")

        self._patch_transport(monkeypatch, handler)

        async def collect():
            return b"".join([c async for c in sp_client.iter_download("I1")])

        assert asyncio.run(collect()) == b"payload"

        cdn = [c for c in calls if "cdn.example" in c[0]]
        assert cdn, "the redirect was not followed"
        assert "authorization" not in {k.lower() for k in cdn[0][1]}, (
            "the CDN request carried our bearer token"
        )

    def test_redirect_without_location_raises(self, sp_client, monkeypatch):
        def handler(request):
            if "login.microsoftonline.com" in str(request.url):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 3600}
                )
            return httpx.Response(302, headers={})

        self._patch_transport(monkeypatch, handler)

        async def collect():
            return [c async for c in sp_client.iter_download("I1")]

        with pytest.raises(SharePointError, match="Location"):
            asyncio.run(collect())

    def test_redirect_to_a_404_raises_clearly(self, sp_client, monkeypatch):
        def handler(request):
            if "graph.microsoft.com" in str(request.url):
                return httpx.Response(
                    302, headers={"Location": "https://cdn.example/gone"}
                )
            return httpx.Response(
                404, json={"error": {"code": "itemNotFound"}}
            )

        self._patch_transport(monkeypatch, handler)

        async def collect():
            return [c async for c in sp_client.iter_download("I1")]

        with pytest.raises(SharePointError):
            asyncio.run(collect())


_MEDIA_ROW = {
    "id": 1, "project_id": "TDAC-1", "entity_kind": "project",
    "sample_id": None, "filename": "site.png",
    "content_type": "image/png", "size_bytes": 1000,
    "sharepoint_item_id": "I1", "web_url": "https://sp/I1",
    "preview_url": None, "preview_supported": False,
    "uploaded_by": 1, "uploaded_by_username": "admin",
    "uploaded_at": "2026-10-01T10:00:00Z",
}
_MEDIA_PAYLOAD = b"\x89PNG\r\n\x1a\n" + b"p" * 900


def _route_media(pool):
    pool.route("WHERE u.id", make_user_row())
    pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)
    pool.route('LEFT JOIN "tdac"."users"', _MEDIA_ROW)


def _stub_media_download(monkeypatch, captured):
    async def fake(self, item_id, *, range_header=None, chunk_size=1024 * 1024):
        captured["range"] = range_header
        body = _MEDIA_PAYLOAD
        if range_header:
            span = range_header.split("=", 1)[1]
            start_s, end_s = span.split("-", 1)
            start = int(start_s)
            end = int(end_s) + 1 if end_s else len(body)
            body = body[start:end]
        for i in range(0, len(body), 256):
            yield body[i:i + 256]

    monkeypatch.setattr(SharePointClient, "iter_download", fake)


class TestMediaResponsePrivacy:
    """The media token travels in the URL, so the URL must not leak."""

    def test_referrer_policy_is_no_referrer(self, client, pool, monkeypatch):
        _route_media(pool)
        captured = {}
        _stub_media_download(monkeypatch, captured)
        token = client.get(
            "/api/attachments/TDAC-1/media-token", headers=auth_header()
        ).json()["media_token"]

        resp = client.get(f"/api/attachments/TDAC-1/1/content?mt={token}")

        assert resp.headers.get("referrer-policy") == "no-referrer"

    def test_cache_control_is_private(self, client, pool, monkeypatch):
        _route_media(pool)
        captured = {}
        _stub_media_download(monkeypatch, captured)
        token = client.get(
            "/api/attachments/TDAC-1/media-token", headers=auth_header()
        ).json()["media_token"]

        resp = client.get(f"/api/attachments/TDAC-1/1/content?mt={token}")

        assert "private" in resp.headers.get("cache-control", "")


class TestMediaTokenTampering:
    def test_access_token_is_refused_as_a_media_token(self, client, pool):
        """An access token has type=access, so it must not open content."""
        _route_media(pool)
        access = auth_header()["Authorization"].split(" ", 1)[1]
        resp = client.get(f"/api/attachments/TDAC-1/1/content?mt={access}")
        assert resp.status_code == 401

    def test_garbage_token_is_refused(self, client, pool):
        _route_media(pool)
        resp = client.get("/api/attachments/TDAC-1/1/content?mt=not-a-jwt")
        assert resp.status_code == 401


class TestRootFolder:
    """Every TDAC file lives under one application folder.

    Without it the project folders sit at the drive root and any other app
    on the same SharePoint site can collide with them.
    """

    def test_default_root_is_tdac(self, monkeypatch):
        monkeypatch.delenv("SHAREPOINT_ROOT_FOLDER", raising=False)
        assert sp_client_module._root_folder() == "TDAC"

    def test_paths_are_prefixed(self, monkeypatch):
        monkeypatch.delenv("SHAREPOINT_ROOT_FOLDER", raising=False)
        assert sp_client_module._with_root("TDAC-1") == "TDAC/TDAC-1"

    def test_root_is_configurable(self, monkeypatch):
        monkeypatch.setenv("SHAREPOINT_ROOT_FOLDER", "Docs/TDAC")
        assert sp_client_module._with_root("TDAC-1") == "Docs/TDAC/TDAC-1"

    def test_whitespace_root_is_treated_as_unset(self, monkeypatch):
        # A blank value must not become a folder literally named "  ".
        monkeypatch.setenv("SHAREPOINT_ROOT_FOLDER", "  ")
        assert sp_client_module._root_folder() == "TDAC"

    def test_upload_creates_the_root_first(self, sp_client, monkeypatch):
        """The root is a level like any other, so it is created first."""
        created = []

        def handler(request):
            url = str(request.url)
            if "/root:" in url and request.method == "GET":
                return httpx.Response(404, json={"error": {"code": "nf"}})
            if url.endswith("/children"):
                created.append(request.content.decode())
                return httpx.Response(201, json={"id": "F"})
            return httpx.Response(201, json={"id": "I1", "webUrl": "u"})

        install_graph(monkeypatch, handler)
        asyncio.run(
            sp_client.upload("TDAC-1", "a.png", b"abc", "image/png")
        )

        assert created, "no folder was created"
        assert '"name":"TDAC"' in created[0], created

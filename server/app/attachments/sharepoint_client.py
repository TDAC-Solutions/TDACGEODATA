"""SharePoint file store for TDAC attachments.

Files live in SharePoint; only metadata goes to PostgreSQL. This module is
the only place that talks to Microsoft Graph, which keeps the API surface
small and makes the whole integration testable by patching one seam.

Design decisions worth knowing:

* SharePoint 2016-era site collections and the modern Graph drive API do not
  mix. ``SHAREPOINT_DRIVE_ID`` is what every call is scoped to, so a legacy
  site needs the OneDrive/SPO migration before this works against it.
* Uploads use an upload *session* for everything above 4 MB. Graph rejects
  a simple PUT above 4 MB outright; photos and site videos are routinely
  larger, so the session path is the normal path, not an edge case.
* Graph's ``/preview`` is best-effort. It 404s for Office documents and
  other formats it cannot render. That is not an error, so it is reported
  as a flag rather than raised.
* Retries are bounded and only for conditions that can succeed later:
  429 and 5xx. A 400 will never succeed, so retrying it just wastes the
  caller's timeout.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LOGIN_BASE = "https://login.microsoftonline.com"

# Graph's simple PUT ceiling. Above this an upload session is mandatory.
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024

# Upload-session chunk size. Graph requires every chunk except the last to
# be a multiple of 320 KiB; 5 MiB satisfies that and keeps chunk counts low.
UPLOAD_CHUNK_SIZE = 5 * 1024 * 1024

# Retry policy for transient Graph failures.
_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5


class SharePointNotConfigured(RuntimeError):
    """Raised when the SharePoint environment variables are absent."""


class SharePointError(RuntimeError):
    """A Graph call failed in a way the caller cannot fix.

    Carries the HTTP status when it came from a response, so callers can
    branch on 404 (absent) or 409 (collision) rather than string-matching
    the message.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# Internal key -> environment variable name. The error message reports the
# env var, because that is what an operator has to set.
_ENV_NAMES = {
    "client_id": "AZURE_CLIENT_ID",
    "client_secret": "AZURE_CLIENT_SECRET",
    "tenant_id": "AZURE_TENANT_ID",
    "site_id": "SHAREPOINT_SITE_ID",
    "drive_id": "SHAREPOINT_DRIVE_ID",
}


def _config() -> Dict[str, Optional[str]]:
    return {key: os.getenv(env) for key, env in _ENV_NAMES.items()}


def is_configured() -> bool:
    """True when every required environment variable is present."""
    return all(_config().values())


def _require_config() -> Dict[str, str]:
    config = _config()
    missing = [k for k, v in config.items() if not v]
    if missing:
        # Names only, never values.
        raise SharePointNotConfigured(
            "SharePoint is not configured. Missing environment "
            f"variable(s): {', '.join(sorted(_ENV_NAMES[k] for k in missing))}."
        )
    return {k: v for k, v in config.items() if v}


def _root_folder() -> str:
    """Application folder under the drive root.

    Without this, every TDAC folder sits directly at the drive root and any
    other app on the same SharePoint site can collide with it. Set
    SHAREPOINT_ROOT_FOLDER to move it. Decide this before the first upload:
    changing it afterwards leaves the old tree behind.
    """
    configured = (os.getenv("SHAREPOINT_ROOT_FOLDER") or "").strip()
    # strip("/") as well, so a trailing slash cannot produce an empty
    # segment, and a blank value falls back to the default rather than
    # becoming a folder named "".
    return configured.strip("/") or "TDAC"


def _with_root(folder: str) -> str:
    """Prefix a project-relative folder with the application root."""
    root = _root_folder()
    relative = folder.strip("/")
    if not root:
        return relative
    return f"{root}/{relative}" if relative else root


class SharePointClient:
    """Async Graph client with a cached app-only access token.

    The token is cached in-process until shortly before it expires, so a
    busy upload page does not mint a new token per request. With more than
    one worker each keeps its own cache, which is harmless — it just means
    one token per worker rather than one per process.
    """

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._lock = asyncio.Lock()
        # One pooled client for every request. A fresh AsyncClient per call
        # meant a 250 MB upload chunked at 5 MiB paid roughly 50 TCP+TLS
        # handshakes, which dominated the transfer time on a field
        # connection. Closed by close_client() on application shutdown so a
        # redeploy does not leak sockets.
        self._client: Optional[httpx.AsyncClient] = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=30.0, read=300.0, write=300.0, pool=30.0
                ),
                limits=httpx.Limits(
                    max_connections=32, max_keepalive_connections=16
                ),
                # Redirects are followed explicitly in iter_download so the
                # Authorization header can be stripped on the second hop.
                follow_redirects=False,
            )
        return self._client

    async def close_client(self) -> None:
        """Release pooled connections on shutdown."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def access_token(self) -> str:
        """Return a valid Graph token, minting one only when needed."""
        async with self._lock:
            now = time.monotonic()
            if self._token and now < self._token_expires_at:
                return self._token

            config = _require_config()
            token, expires_in = await self._fetch_token(config)
            # Refresh 60s early so a request never starts with a token that
            # expires mid-flight.
            self._token = token
            self._token_expires_at = now + max(expires_in - 60, 30)
            return token

    async def _fetch_token(
        self, config: Dict[str, str]
    ) -> Tuple[str, int]:
        """Client-credentials grant. No user is involved at any point."""
        response = await self._http().post(
            f"{LOGIN_BASE}/{config['tenant_id']}/oauth2/v2.0/token",
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )

        if response.status_code != 200:
            # Never echo the response body: it can contain tenant details.
            raise SharePointError(
                f"Azure AD token request failed "
                f"(HTTP {response.status_code}). Check AZURE_CLIENT_ID, "
                f"AZURE_CLIENT_SECRET and AZURE_TENANT_ID."
            )

        try:
            payload = response.json()
        except ValueError:
            # A captive portal, TLS-intercepting proxy or corporate gateway
            # can answer with an HTML page instead of the token JSON. Without
            # this guard the JSONDecodeError escaped the router's
            # SharePointError handler and surfaced as an opaque 500.
            raise SharePointError(
                "Azure AD token endpoint returned a non-JSON response. "
                "Check for a proxy or captive portal in front of the "
                "token endpoint."
            ) from None

        token = payload.get("access_token")
        if not token:
            raise SharePointError(
                "Azure AD returned no access_token. Check that the app "
                "registration is in this tenant and admin consent was "
                "granted for the Graph application permissions."
            )
        return token, int(payload.get("expires_in", 3600))

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[bytes] = None,
        json: Optional[Dict[str, Any]] = None,
        allow: Tuple[int, ...] = (200, 201, 204),
    ) -> httpx.Response:
        """Issue one Graph call, retrying only transient failures."""
        last_error = "unknown"

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            token = await self.access_token()
            request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}

            response = await self._http().request(
                method,
                url,
                headers=request_headers,
                content=content,
                json=json,
            )

            if response.status_code in allow:
                return response

            # 429 and 5xx can succeed on a retry; anything else will not.
            transient = response.status_code == 429 or response.status_code >= 500
            if not transient or attempt == _MAX_ATTEMPTS:
                detail = _safe_detail(response)
                raise SharePointError(
                    f"SharePoint {method} {url.split('?')[0]} failed "
                    f"(HTTP {response.status_code}): {detail}",
                    status_code=response.status_code,
                )

            retry_after = response.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after and retry_after.isdigit()
                else _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            )
            last_error = f"HTTP {response.status_code}"
            logger.warning(
                "Graph %s %s transient failure (%s); retry %s/%s in %.1fs",
                method, url, last_error, attempt, _MAX_ATTEMPTS, delay,
            )
            await asyncio.sleep(delay)

        raise SharePointError(f"SharePoint request failed: {last_error}")

    # -- folder / item operations ------------------------------------

    @staticmethod
    def _encode(path: str) -> str:
        """Percent-encode a SharePoint path, one safe segment at a time.

        Graph's ``root:/a/b`` syntax takes the path as-is, so anything that
        could re-interpret the path has to be neutralised:

        * a ``/`` inside a name becomes ``%2F`` so it cannot add a segment;
        * ``.`` and ``..`` are replaced outright, because percent-encoding
          them is not enough -- Graph resolves them server-side, so a
          literal ``..`` would climb out of the project folder;
        * the rest are escaped so a space or ``?`` cannot truncate a URL.
        """
        segments = []
        for segment in path.split("/"):
            # An empty segment is dropped, not encoded. Substituting "%20"
            # here produced root:/%20/children when creating the first
            # folder, because its parent is the empty string.
            if not segment:
                continue
            if segment in (".", ".."):
                # Path traversal has no legitimate use here.
                segments.append("%2E" * len(segment))
                continue
            # No "/" replacement: split("/") already removed every
            # separator, so there is nothing left to encode. ":" is escaped
            # defensively even though _safe_filename strips it upstream.
            encoded = (
                segment.replace("%", "%25")
                .replace(" ", "%20")
                .replace("?", "%3F")
                .replace("#", "%23")
                .replace(":", "%3A")
            )
            segments.append(encoded)
        return "/".join(segments)

    async def create_folder(self, folder: str) -> Dict[str, Any]:
        """Ensure /{folder} exists, creating any missing level.

        Walks the path one segment at a time. Graph cannot create a
        multi-segment path in a single POST: driveItem.name may not contain
        "/", so posting "TDAC-1/samples/TDAC-1-16" is rejected and every
        sample upload failed. Walking segments is what makes the nested
        sample folders work at all.

        conflictBehavior=fail is deliberate. With rename, two users whose
        first upload for the same project races would create TDAC-1 and
        TDAC-1 1, silently splitting one project's files across two
        folders. Failing the second create and re-reading keeps the
        invariant that a project maps to exactly one folder.
        """
        config = _require_config()
        drive_id = config["drive_id"]

        segments = [s for s in _with_root(folder).split("/") if s]
        if not segments:
            raise SharePointError("Cannot create a folder with an empty path.")

        parent = ""
        result: Dict[str, Any] = {}

        for segment in segments:
            encoded_parent = self._encode(parent)
            encoded_name = self._encode(segment)
            base = f"{encoded_parent}/" if encoded_parent else ""
            item_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{base}{encoded_name}"
            # The trailing colon is load-bearing. Graph reads everything after
            # "root:/" up to the next "/" as the item path, so
            # "root:/TDAC/children" addresses an item named "children" inside
            # TDAC -- it 404s on read and answers 400 invalidRequest on POST.
            # "root:/TDAC:/children" terminates the path and is the collection
            # under it.
            children_url = (
                f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded_parent}:/children"
                if encoded_parent
                else f"{GRAPH_BASE}/drives/{drive_id}/root/children"
            )

            try:
                result = await self._item_json("GET", item_url, allow=(200,))
            except SharePointError as error:
                # Only 404 means "absent, create it". A 403 or 400 means
                # something is genuinely wrong and must surface, rather
                # than be mistaken for a missing folder.
                if error.status_code != 404:
                    raise

                try:
                    result = await self._item_json(
                        "POST",
                        children_url,
                        json={
                            # The bare segment, never the full path.
                            "name": segment,
                            "folder": {},
                            "@microsoft.graph.conflictBehavior": "fail",
                        },
                        allow=(200, 201),
                    )
                except SharePointError as create_error:
                    if create_error.status_code != 409:
                        raise
                    # Lost the race: it exists now, so use it.
                    logger.info(
                        "SharePoint folder /%s/%s created concurrently; "
                        "reusing it.",
                        parent, segment,
                    )
                    result = await self._item_json(
                        "GET", item_url, allow=(200,)
                    )
                else:
                    logger.info(
                        "Created SharePoint folder /%s/%s", parent, segment
                    )

            parent = f"{parent}/{segment}" if parent else segment

        return result

    async def _item_json(
        self,
        method: str,
        url: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        allow: Tuple[int, ...] = (200, 201),
    ) -> Dict[str, Any]:
        response = await self._request(method, url, json=json, allow=allow)
        if not response.content:
            return {}
        return response.json()

    async def upload(
        self, folder: str, filename: str, data: bytes, content_type: str
    ) -> Dict[str, Any]:
        """Upload one file, choosing simple PUT or an upload session."""
        # create_folder roots internally, so it gets the relative path.
        # The item URL needs the rooted form, otherwise the file would land
        # outside the tree just created.
        await self.create_folder(folder)
        rooted = _with_root(folder)

        config = _require_config()
        drive_id = config["drive_id"]
        item_path = self._encode(f"{rooted}/{filename}")
        item_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{item_path}"

        if len(data) <= SIMPLE_UPLOAD_LIMIT:
            return await self._put_content(item_url, data, content_type)

        return await self._upload_session(item_url, data, content_type)

    async def _put_content(
        self, url: str, data: bytes, content_type: str
    ) -> Dict[str, Any]:
        response = await self._request(
            "PUT",
            f"{url}:/content",
            headers={"Content-Type": content_type},
            content=data,
            allow=(200, 201),
        )
        return response.json() if response.content else {}

    async def _upload_session(
        self, item_url: str, data: bytes, content_type: str
    ) -> Dict[str, Any]:
        """Chunked upload for anything over 4 MB.

        The uploadUrl Graph returns is pre-authorised and scoped to this
        one item; it must never be logged or persisted.
        """
        session = await self._item_json(
            "POST", f"{item_url}:/createUploadSession"
        )
        upload_url = session.get("uploadUrl")
        if not upload_url:
            raise SharePointError(
                "Graph did not return an uploadUrl for the large-file "
                "upload session."
            )

        total = len(data)
        start = 0
        last_response = None

        while start < total:
            end = min(start + UPLOAD_CHUNK_SIZE, total)
            chunk = data[start:end]

            last_response = await self._upload_chunk(
                upload_url,
                content_type,
                f"bytes {start}-{end - 1}/{total}",
                chunk,
                allow=(200, 201, 202),
            )
            start = end

        # _upload_session is only reached for data over SIMPLE_UPLOAD_LIMIT,
        # so the loop above always runs and last_response is always set.

        # Graph returns the finished driveItem on the LAST chunk PUT, so
        # there is nothing left to fetch. Issuing a follow-up GET on the
        # uploadUrl is wrong: the session is complete and that URL is
        # single-use, so it answers 404/410 and failed every upload over
        # 4 MB. 202 means "chunk accepted, more to come"; 200/201 on the
        # final range means "upload finished".
        if last_response.status_code not in (200, 201):
            raise SharePointError(
                "Upload session did not complete "
                f"(HTTP {last_response.status_code})."
            )

        return last_response.json() if last_response.content else {}

    async def _upload_chunk(
        self,
        upload_url: str,
        content_type: str,
        content_range: str,
        chunk: bytes,
        allow: Tuple[int, ...],
    ) -> httpx.Response:
        """PUT one chunk of an upload session.

        The uploadUrl is pre-authorised, but a Bearer header is still sent:
        it costs nothing and keeps the call working if the tenant ever
        requires it. This URL is a bearer-equivalent secret and is never
        logged or persisted.
        """
        return await self._request(
            "PUT",
            upload_url,
            headers={
                "Content-Type": content_type,
                "Content-Range": content_range,
            },
            content=chunk,
            allow=allow,
        )

    async def upload_stream(
        self,
        folder: str,
        filename: str,
        chunks: AsyncIterator[bytes],
        total_size: int,
        content_type: str,
    ) -> Dict[str, Any]:
        """Stream a file to Graph without buffering it in this process.

        The buffered path read the whole body into a bytes object before the
        first Graph chunk was sent, so a 250 MB site video occupied 250 MB of
        FastAPI memory for the duration. Handing each chunk to Graph as it
        arrives keeps peak memory at roughly one chunk regardless of file
        size, which is the difference between working and not working on a
        small ECS task.

        Under the simple-PUT ceiling the body is assembled, because a single
        PUT is fewer round trips and the size is already bounded at 4 MB.
        """
        await self.create_folder(folder)
        rooted = _with_root(folder)

        config = _require_config()
        item_path = self._encode(f"{rooted}/{filename}")
        item_url = f"{GRAPH_BASE}/drives/{config['drive_id']}/root:/{item_path}"

        if total_size <= SIMPLE_UPLOAD_LIMIT:
            data = b"".join([chunk async for chunk in chunks])
            return await self._put_content(item_url, data, content_type)

        session = await self._item_json(
            "POST", f"{item_url}:/createUploadSession"
        )
        upload_url = session.get("uploadUrl")
        if not upload_url:
            raise SharePointError(
                "Graph did not return an uploadUrl for the large-file "
                "upload session."
            )

        buffer = bytearray()
        offset = 0
        last_response: Optional[httpx.Response] = None

        async for chunk in chunks:
            buffer.extend(chunk)
            # Every chunk but the last must be a multiple of 320 KiB;
            # UPLOAD_CHUNK_SIZE is 5 MiB, which satisfies that.
            while len(buffer) >= UPLOAD_CHUNK_SIZE:
                to_send = bytes(buffer[:UPLOAD_CHUNK_SIZE])
                del buffer[:UPLOAD_CHUNK_SIZE]
                end = offset + len(to_send) - 1
                last_response = await self._upload_chunk(
                    upload_url,
                    content_type,
                    f"bytes={offset}-{end}/{total_size}",
                    to_send,
                    allow=(200, 201, 202),
                )
                offset += len(to_send)

        # The tail, which may be short. Being the last range is what makes
        # it legitimate.
        if buffer:
            to_send = bytes(buffer)
            end = offset + len(to_send) - 1
            last_response = await self._upload_chunk(
                upload_url,
                content_type,
                f"bytes={offset}-{end}/{total_size}",
                to_send,
                allow=(200, 201, 202),
            )

        if last_response is None:
            raise SharePointError("Upload session had no content to send.")

        # The finished driveItem arrives on the last chunk PUT. The
        # uploadUrl is single-use afterwards, so there is nothing to fetch.
        if last_response.status_code not in (200, 201):
            raise SharePointError(
                "Upload session did not complete "
                f"(HTTP {last_response.status_code}).",
                status_code=last_response.status_code,
            )

        return last_response.json() if last_response.content else {}

    async def iter_download(
        self,
        item_id: str,
        *,
        range_header: Optional[str] = None,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """Stream an item's raw bytes from Graph.

        The browser cannot be handed a SharePoint URL for an <img> or
        <video>: webUrl and the /preview getUrl are both HTML viewer pages.
        Only item content is image bytes. So the backend streams it and the
        browser fetches from us, which also keeps the file behind auth.

        Graph answers /content with a 302 to a short-lived CDN URL, and
        httpx does not follow redirects inside a stream. The redirect is
        followed manually so the Authorization header can be stripped before
        the request is re-issued: the CDN neither needs it nor should log it.

        Streamed rather than buffered, so a 200 MB site video never sits in
        this process's memory. When range_header is given it is forwarded to
        Graph, which answers 206 with just that slice.
        """
        config = _require_config()
        drive_id = config["drive_id"]
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"

        token = await self.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        if range_header:
            headers["Range"] = range_header

        client = self._http()

        # Not routed through _request: that buffers the body, which is
        # exactly what this path exists to avoid.
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request, stream=True)

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise SharePointError(
                    "Graph returned a redirect with no Location header for "
                    "the content download."
                )
            # Second hop, deliberately without the Authorization header.
            cdn_request = client.build_request("GET", location)
            response = await client.send(cdn_request, stream=True)

        try:
            if response.status_code not in (200, 206):
                await response.aread()
                detail = _safe_detail(response)
                raise SharePointError(
                    f"SharePoint content download failed "
                    f"(HTTP {response.status_code}): {detail}",
                    status_code=response.status_code,
                )
            async for chunk in response.aiter_bytes(chunk_size):
                yield chunk
        finally:
            await response.aclose()

    async def download_bytes(
        self, item_id: str, max_bytes: int = 5 * 1024 * 1024
    ) -> bytes:
        """Fetch an item's bytes through the normal request path.

        Uses _request, so it inherits the retry policy and stays injectable
        in tests. Only for small items; iter_download is the streaming path
        for real files.
        """
        config = _require_config()
        drive_id = config["drive_id"]
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"

        response = await self._request("GET", url, allow=(200, 302))
        content = response.content

        if len(content) > max_bytes:
            raise SharePointError(
                f"Item is {len(content)} bytes, over the "
                f"{max_bytes} byte inline limit; use the streaming path."
            )
        return content

    async def preview_url(self, item_id: str) -> Tuple[Optional[str], bool]:
        """Return (preview_url, supported).

        Graph's /preview is best-effort: Office documents and some binary
        formats return 404 because Graph has no renderer for them. That is
        an expected outcome, not a failure, so the caller can fall back to
        the web_url or an icon.
        """
        config = _require_config()
        drive_id = config["drive_id"]

        try:
            payload = await self._item_json(
                "POST",
                f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/preview",
                allow=(200,),
            )
        except SharePointError as error:
            logger.info(
                "No SharePoint preview for item %s (%s); "
                "falling back to web_url.",
                item_id, _first_line(str(error)),
            )
            return None, False

        return payload.get("getUrl"), bool(payload.get("getUrl"))


def _safe_detail(response: httpx.Response) -> str:
    """A short, non-secret explanation of a Graph failure."""
    try:
        payload = response.json()
        error = payload.get("error", {})
        message = error.get("message") or payload.get("error_description") or ""
        code = error.get("code", "")
        return f"{code}: {message}"[:400] if code else str(message)[:400]
    except Exception:
        return response.text[:200]


def _first_line(text: str) -> str:
    return text.split("\n", 1)[0][:200]


# Module-level singleton: one token cache for the process.
sharepoint = SharePointClient()

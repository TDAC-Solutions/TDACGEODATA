"""Project attachments: SharePoint as the file store, PostgreSQL as metadata.

Layering, matching ``spreadsheet_import``:

    sharepoint_client.py  Graph transport. Token, folder, upload, preview.
                          No database, no FastAPI. Sole owner of Graph URLs.
    service.py            Metadata in PostgreSQL plus the access rules.
    router.py             HTTP surface: upload, list, fetch, delete.

Parsing and transport stay separate so the client can be exercised against
a fake HTTP transport without a database, and so the metadata layer can be
tested without SharePoint.
"""

from app.attachments.sharepoint_client import (
    SharePointError,
    SharePointNotConfigured,
    is_configured,
    sharepoint,
)

__all__ = [
    "SharePointError",
    "SharePointNotConfigured",
    "is_configured",
    "sharepoint",
]

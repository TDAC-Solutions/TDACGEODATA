# SharePoint attachments — server configuration
#
# Files for a project (site photos, videos, drawings, documents) are stored in
# SharePoint under a folder named after the project id. PostgreSQL holds only
# metadata. This is what keeps the database lean while using storage the client
# already pays for.
#
# ---------------------------------------------------------------------------
# 1. Register the app (one-time, Azure portal)
# ---------------------------------------------------------------------------
#   App registrations -> New registration
#     Name:                TDAC-SharePoint-Integration
#     Accounts:            This organizational directory only
#     Redirect URI:        none needed (server-to-server)
#
#   Certificates & secrets -> New client secret
#     Copy the Value immediately. It is shown once.
#
#   API permissions -> Microsoft Graph -> Application permissions
#     Sites.Selected          (preferred — see note below)
#       or Sites.ReadWrite.All + Files.ReadWrite.All
#     Click "Grant admin consent".
#
#   Sites.Selected is the tighter choice: it grants access to exactly one site.
# Enable it with a single POST after the app is consented:
#
#   POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissionGrants
#   Authorization: Bearer <app-token>
#   Content-Type: application/json
#
#   {
#     "roles": ["write"],
#     "grantee": {
#       "application": { "id": "<AZURE_CLIENT_ID>", "displayName": "TDAC" }
#     }
#   }
#
# Using Sites.ReadWrite.All instead? Nothing to do — just skip this step, but
# understand that the app can then read and write every site in the tenant.
#
# ---------------------------------------------------------------------------
# 2. Find the site and drive ids
# ---------------------------------------------------------------------------
# Use Graph Explorer (https://developer.microsoft.com/graph/graph-explorer),
# signed in as a tenant admin, "Application" permissions:
#
#   GET https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com:/sites/Projects
#     -> copy "id"                    into SHAREPOINT_SITE_ID
#
#   GET https://graph.microsoft.com/v1.0/sites/{site-id}/drives
#     -> copy the "id" of the drive  into SHAREPOINT_DRIVE_ID
#        (the one named after your document library, usually "Documents")
#
# The site id looks like:
#   contoso.sharepoint.com,00000000-0000-0000-0000-000000000000,00000000-...
#
# ---------------------------------------------------------------------------
# 3. Environment variables — add these five to server/.env
# ---------------------------------------------------------------------------
# AZURE_CLIENT_ID=<application-client-id>
# AZURE_CLIENT_SECRET=<the secret value>
# AZURE_TENANT_ID=<directory-tenant-id>
# SHAREPOINT_SITE_ID=<site-id>
# SHAREPOINT_DRIVE_ID=<drive-id>
#
# Optional, and decide it BEFORE the first upload:
# SHAREPOINT_ROOT_FOLDER=TDAC
#
# Every file lives under this application folder, so TDAC cannot collide
# with another app sharing the same SharePoint site:
#
#   /TDAC/{project_id}/{filename}
#   /TDAC/{project_id}/samples/{sample_id}/{filename}
#
# Changing it after files exist starts a new tree and leaves the old one
# where it is; it is not a move.
#
# Validate them without printing any secret:
#
#   curl -s -X POST https://login.microsoftonline.com/$AZURE_TENANT_ID/oauth2/v2.0/token \
#     -d client_id=$AZURE_CLIENT_ID \
#     -d client_secret="$AZURE_CLIENT_SECRET" \
#     -d scope=https://graph.microsoft.com/.default \
#     -d grant_type=client_credentials | head -c 60
#
# Expect access_token. "invalid_client" means the id/secret pair is wrong.
#
# The backend exposes a readiness probe that reports only whether all five are
# present, never their values:
#
#   curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/attachments/health
#   {"configured": true}
#
# ---------------------------------------------------------------------------
# 4. AWS: injecting the secrets
# ---------------------------------------------------------------------------
# Nothing is free-and-secure at once, so this is the one line item worth the
# cost: AWS Secrets Manager is $0.40 per secret per month. Five secrets is
# about $2/month. Do not put these five values in the task definition's plain
# "environment" block — that is readable by anyone with task-definition access.
#
#   aws secretsmanager create-secret --name tdac/azure-client-id     --secret-string '<id>'
#   aws secretsmanager create-secret --name tdac/azure-client-secret --secret-string '<secret>'
#   aws secretsmanager create-secret --name tdac/azure-tenant-id    --secret-string '<tenant>'
#   aws secretsmanager create-secret --name tdac/sharepoint-site-id --secret-string '<site>'
#   aws secretsmanager create-secret --name tdac/sharepoint-drive-id --secret-string '<drive>'
#
# ECS task definition:
#
#   "secrets": [
#     { "name": "AZURE_CLIENT_ID",     "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:tdac/azure-client-id" },
#     { "name": "AZURE_CLIENT_SECRET", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:tdac/azure-client-secret" },
#     { "name": "AZURE_TENANT_ID",     "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:tdac/azure-tenant-id" },
#     { "name": "SHAREPOINT_SITE_ID",  "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:tdac/sharepoint-site-id" },
#     { "name": "SHAREPOINT_DRIVE_ID", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:tdac/sharepoint-drive-id" }
#   ]
#
# For local and test work, plain server/.env is fine — it is gitignored.
#
# ---------------------------------------------------------------------------
# 5. What the client needs to know: nothing
# ---------------------------------------------------------------------------
# The browser never sees the tenant, the client id or the secret. The React app
# calls /api/attachments on this backend; the backend talks to Graph. There is no
# reason to expose Azure credentials to the frontend.
#
# ---------------------------------------------------------------------------
# 6. Limits and behaviour worth knowing
# ---------------------------------------------------------------------------
#   * Files over 4 MB use a Graph upload session automatically (chunked, 5 MB
#     per chunk, resumable). No configuration needed.
#   * Hard cap is 250 MB (server/app/attachments/service.py). Raise it there if
#     the client needs larger site videos.
#   * Images and video are served by GET /api/attachments/{project}/{id}/content,
#     which streams the item's real bytes from Graph. SharePoint's webUrl and
#     the /preview getUrl are both HTML viewer pages, so pointing an <img> or
#     <video> at either renders a broken element. Streaming also keeps the
#     file behind TDAC auth and avoids exposing Graph's short-lived URLs.
#   * Graph cannot preview Office documents (.docx, .xlsx, .pptx) or arbitrary
#     binaries. Those are stored and linked, and the UI offers "Open in
#     SharePoint" plus a "Refresh preview" button instead of a broken frame.
#   * Graph preview URLs expire in roughly an hour. The panel offers
#     "Refresh preview", which mints a fresh URL and stores it.
#   * A project folder is created automatically on first upload. The folder
#     name is the project id, e.g. /TDAC-2026-041/.
#   * "Remove" in the UI deletes only the metadata row. The file stays in
#     SharePoint on purpose — see server/app/attachments/service.py.
#   * Access is role-based: any signed-in user who can open a project can see
#     its attachments. TDAC has no per-user project scoping, and this does not
#     introduce one. Raise that before the client stores anything sensitive.
#
# ---------------------------------------------------------------------------
# 7. Database
# ---------------------------------------------------------------------------
# The table already exists locally. For a fresh environment run these in
# order — migration_spt_sample_identity.sql adds entity_kind and sample_id,
# without which every attachment endpoint fails with UndefinedColumn, so it
# must run after migration_attachments.sql:
#
#   psql -f server/scripts/migration_attachments.sql
#   psql -f server/scripts/migration_spt_sample_identity.sql
#
# If you use the Field Data > Rock module, also run:
#
#   psql -f server/scripts/migration_rock.sql
#
# It holds no file bytes: filename, MIME type, size, the SharePoint item id,
# the web url, whether a preview exists, and who uploaded it.

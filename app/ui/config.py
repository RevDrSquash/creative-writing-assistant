"""Shared NiceGUI application configuration."""

APP_TITLE = "Writing Agent"

# Signs the session cookie that backs `app.storage.user`. Local-only and single-user
# for now; move to an env var with a random value before any shared deployment.
STORAGE_SECRET = "writing-agent-local-storage-secret"

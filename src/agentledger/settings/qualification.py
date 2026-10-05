"""Isolated synthetic visual qualification only, never a deployment profile."""
from .development import *  # noqa: F403
from .development import BASE_DIR
DEBUG=False
ALLOWED_HOSTS=['localhost','127.0.0.1']
STATIC_ROOT='/tmp/stewardence-qa-static'
CORE_WORKFLOWS_ENABLED=False
QUICKBOOKS_PREVIEW_ENABLED=False
MICROSOFT_PREVIEW_ENABLED=False
XERO_PREVIEW_ENABLED=False
AUTOMATION_ENABLED=False

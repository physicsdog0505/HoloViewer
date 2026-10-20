"""Read-only Data Lifecycle Admin contracts, controller and Phase 1 shell."""

from .auth import AdminAuthenticator, AuthResult
from .contracts import build_sync_monitor, build_system_health
from .dashboard import DashboardController
from .http import DashboardApplication
from .integration import build_internal_admin_application

__all__ = [
    "AdminAuthenticator", "AuthResult", "DashboardApplication", "DashboardController",
    "build_internal_admin_application", "build_sync_monitor", "build_system_health",
]

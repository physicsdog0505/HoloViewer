"""Host-owned composition for an internal read-only Admin application."""
from __future__ import annotations

from .host_boundary import evaluate_internal_exposure
from .http import DashboardApplication
from .isolated import AuthenticatedDashboard


def build_internal_admin_application(*, controller, authenticator, exposure_config):
    """Compose only after host isolation is proven; never mounts or binds a socket."""
    decision = evaluate_internal_exposure(exposure_config)
    if not decision.allowed:
        raise RuntimeError(decision.error_code or "network_isolation_unproven")
    return AuthenticatedDashboard(DashboardApplication(controller), authenticator)

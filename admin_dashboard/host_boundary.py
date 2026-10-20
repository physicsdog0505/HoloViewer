"""Host-side exposure policy for a future running 8501 Admin mount."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress


@dataclass(frozen=True)
class InternalExposureConfig:
    bind_host: str = "127.0.0.1"
    behind_authenticated_proxy: bool = False
    internal_network_proven: bool = False
    public_route_exposed: bool = False


@dataclass(frozen=True)
class IsolationDecision:
    allowed: bool
    error_code: str | None
    mode: str


def evaluate_internal_exposure(config: InternalExposureConfig) -> IsolationDecision:
    if config.public_route_exposed:
        return IsolationDecision(False, "public_route_forbidden", "denied")
    if config.bind_host in {"0.0.0.0", "::", ""}:
        return IsolationDecision(False, "wildcard_bind_unproven", "denied")
    try:
        ip = ipaddress.ip_address(config.bind_host)
    except ValueError:
        # Hostnames require explicit internal network + authenticated proxy proof.
        if config.behind_authenticated_proxy and config.internal_network_proven:
            return IsolationDecision(True, None, "authenticated_internal_proxy")
        return IsolationDecision(False, "network_isolation_unproven", "denied")
    if ip.is_loopback:
        return IsolationDecision(True, None, "loopback")
    if config.behind_authenticated_proxy and config.internal_network_proven and ip.is_private:
        return IsolationDecision(True, None, "authenticated_internal_proxy")
    return IsolationDecision(False, "network_isolation_unproven", "denied")

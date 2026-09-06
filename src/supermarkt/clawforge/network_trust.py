"""Explicit trusted-network registration and risk scoring.

This module is intentionally provider agnostic.  Technology names are useful
for inventory and matching, but they never grant trust by themselves.  Only a
network with a verified registration can contribute the trusted-infrastructure
score.
"""

from __future__ import annotations

import ipaddress
import json
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable


class NetworkType(StrEnum):
    TAILSCALE = "tailscale"
    NETBIRD = "netbird"
    VLAN = "vlan"
    VPN = "vpn"
    IP_RANGE = "ip_range"
    ASN = "asn"
    BGP = "bgp"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REVOKED = "revoked"


class BGPStatus(StrEnum):
    STABLE = "stable"
    CHANGED = "changed"
    ANOMALOUS = "anomalous"
    UNKNOWN = "unknown"


class RPKIStatus(StrEnum):
    VALID = "valid"
    UNKNOWN = "unknown"
    INVALID = "invalid"


def _tuple(values: Iterable[Any] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TrustedNetwork:
    """An administrator-owned network registration.

    ``status`` is kept in the object so it can be displayed in a dashboard,
    but callers should use :meth:`TrustedNetworkRegistry.verify` and
    :meth:`TrustedNetworkRegistry.revoke` to change it.
    """

    name: str
    type: NetworkType | str
    identifier: str = ""
    networks: tuple[str, ...] = ()
    network: str = ""
    node_identities: tuple[str, ...] = ()
    device_tags: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    policies: tuple[str, ...] = ()
    status: VerificationStatus | str = VerificationStatus.PENDING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=_now)
    verified_at: datetime | None = None
    last_activity: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", NetworkType(self.type))
        object.__setattr__(self, "status", VerificationStatus(self.status))
        object.__setattr__(self, "networks", _tuple(self.networks))
        if self.network and self.network not in self.networks:
            object.__setattr__(self, "networks", (*self.networks, self.network))
        object.__setattr__(self, "node_identities", _tuple(self.node_identities))
        object.__setattr__(self, "device_tags", _tuple(self.device_tags))
        object.__setattr__(self, "groups", _tuple(self.groups))
        object.__setattr__(self, "policies", _tuple(self.policies))
        if self.status is VerificationStatus.VERIFIED and self.verified_at is None:
            object.__setattr__(self, "verified_at", _now())

    @property
    def verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["type"] = self.type.value
        value["status"] = self.status.value
        for key in ("created_at", "verified_at", "last_activity"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value


@dataclass(frozen=True)
class NetworkObservation:
    """Signals collected for one IP, node, peer, or route."""

    ip: str = ""
    network_type: NetworkType | str | None = None
    identifier: str = ""
    node_identity: str = ""
    node_id: str = ""
    peer_id: str = ""
    tailnet_id: str = ""
    network_id: str = ""
    tunnel_id: str = ""
    device_tags: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    ip_reputation: int = 0
    asn_reputation: int = 0
    threat_intelligence: int = 0
    behavior: int = 0
    bgp_anomalies: int = 0
    history: int = 0
    asn: str = ""
    prefix: str = ""
    provider: str = ""
    bgp_status: BGPStatus | str = BGPStatus.UNKNOWN
    rpki_status: RPKIStatus | str = RPKIStatus.UNKNOWN
    unusual_countries: bool = False
    new_login_patterns: bool = False
    mass_scans: bool = False

    def __post_init__(self) -> None:
        if not self.identifier:
            for value in (self.tailnet_id, self.network_id, self.tunnel_id):
                if value:
                    object.__setattr__(self, "identifier", value)
                    break
        if not self.node_identity:
            for value in (self.node_id, self.peer_id):
                if value:
                    object.__setattr__(self, "node_identity", value)
                    break
        if self.network_type is not None:
            object.__setattr__(self, "network_type", NetworkType(self.network_type))
        object.__setattr__(self, "device_tags", _tuple(self.device_tags))
        object.__setattr__(self, "groups", _tuple(self.groups))
        object.__setattr__(self, "bgp_status", BGPStatus(self.bgp_status))
        object.__setattr__(self, "rpki_status", RPKIStatus(self.rpki_status))


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: int
    trust_score: int
    negative_score: int
    trust_adjustment: int
    trusted_network_id: str | None = None
    trusted_network_name: str | None = None
    matched_node: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def score(self) -> int:
        """Convenience alias used by dashboard consumers."""
        return self.risk_score

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


def _bounded(value: int | float, maximum: int) -> int:
    return max(0, min(maximum, int(value)))


def _ip_matches(ip: str, networks: Iterable[str]) -> bool:
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for value in networks:
        try:
            if address in ipaddress.ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


class TrustedNetworkRegistry:
    """In-memory registry for explicitly registered infrastructure.

    Persistence is intentionally left to the caller; :meth:`to_json` and
    :meth:`from_json` make it straightforward to store the registry in the
    application's existing database or configuration system.
    """

    def __init__(self, networks: Iterable[TrustedNetwork] = ()) -> None:
        self._networks: dict[str, TrustedNetwork] = {network.id: network for network in networks}

    def register(
        self,
        registration: TrustedNetwork | None = None,
        *,
        name: str | None = None,
        type: NetworkType | str | None = None,
        identifier: str = "",
        networks: Iterable[str] = (),
        network: TrustedNetwork | str | Iterable[str] | None = None,
        node_identities: Iterable[str] = (),
        device_tags: Iterable[str] = (),
        groups: Iterable[str] = (),
        policies: Iterable[str] = (),
        admin_confirmed: bool = False,
        status: VerificationStatus | str | None = None,
    ) -> TrustedNetwork:
        """Register infrastructure; verification requires explicit confirmation.

        Passing ``admin_confirmed=True`` is the explicit registration action
        and creates a verified entry.  The default is pending, which prevents
        accidental trust when inventory data is merely imported.
        """
        # ``network=TrustedNetwork(...)`` remains a convenient keyword form;
        # a string/iterable is an alias for the singular network range field.
        if registration is None and isinstance(network, TrustedNetwork):
            registration = network
            network = None
        if registration is None:
            if not name or type is None:
                raise ValueError("name and type are required")
            requested_status = VerificationStatus(status) if status is not None else VerificationStatus.PENDING
            # Supplying a verified status is itself an explicit registration
            # action; ordinary inventory imports remain pending by default.
            if requested_status is VerificationStatus.VERIFIED:
                admin_confirmed = True
            range_values = tuple(networks)
            if network is not None and not isinstance(network, str):
                range_values = (*range_values, *tuple(network))
            registration = TrustedNetwork(
                name=name,
                type=type,
                identifier=identifier,
                networks=range_values,
                network=network if isinstance(network, str) else "",
                node_identities=tuple(node_identities),
                device_tags=tuple(device_tags),
                groups=tuple(groups),
                policies=tuple(policies),
                status=VerificationStatus.VERIFIED if admin_confirmed else requested_status,
            )
        elif admin_confirmed and not registration.verified:
            registration = self._replace(registration, status=VerificationStatus.VERIFIED, verified_at=_now())
        self._networks[registration.id] = registration
        return registration

    def verify(self, network_id: str) -> TrustedNetwork:
        network = self.get(network_id)
        if network is None:
            raise KeyError(network_id)
        verified = self._replace(network, status=VerificationStatus.VERIFIED, verified_at=_now())
        self._networks[network_id] = verified
        return verified

    def revoke(self, network_id: str) -> TrustedNetwork:
        network = self.get(network_id)
        if network is None:
            raise KeyError(network_id)
        revoked = self._replace(network, status=VerificationStatus.REVOKED)
        self._networks[network_id] = revoked
        return revoked

    def get(self, network_id: str) -> TrustedNetwork | None:
        return self._networks.get(network_id)

    def list(self, *, verified_only: bool = False) -> tuple[TrustedNetwork, ...]:
        values = tuple(self._networks.values())
        if verified_only:
            return tuple(network for network in values if network.verified)
        return values

    def match(self, observation: NetworkObservation) -> tuple[TrustedNetwork | None, bool]:
        """Return the verified registration and whether its node is known.

        A matching type (for example, ``tailscale``) is never sufficient.  An
        identifier, IP range, ASN/prefix, or explicitly registered identity
        must match a verified registration.
        """
        for network in self.list(verified_only=True):
            if not self._matches(network, observation):
                continue
            node_match = bool(observation.node_identity and observation.node_identity in network.node_identities)
            return network, node_match
        return None, False

    @staticmethod
    def _matches(network: TrustedNetwork, observation: NetworkObservation) -> bool:
        if observation.identifier and network.identifier and observation.identifier.casefold() == network.identifier.casefold():
            return True
        if observation.node_identity and observation.node_identity in network.node_identities:
            return True
        if set(observation.device_tags) & set(network.device_tags):
            return True
        if set(observation.groups) & set(network.groups):
            return True
        if _ip_matches(observation.ip, network.networks):
            return True
        # ASN registrations commonly identify the ASN as AS1234 or 1234.
        if network.type is NetworkType.ASN and observation.asn:
            return observation.asn.casefold().removeprefix("as") == network.identifier.casefold().removeprefix("as")
        if network.type is NetworkType.BGP and observation.prefix and network.identifier:
            try:
                return ipaddress.ip_network(observation.prefix, strict=False).subnet_of(ipaddress.ip_network(network.identifier, strict=False))
            except ValueError:
                return observation.prefix == network.identifier
        return False

    def dashboard(self) -> list[dict[str, Any]]:
        return [
            {
                "id": network.id,
                "name": network.name,
                "type": network.type.value,
                "identifier": network.identifier,
                "networks": list(network.networks),
                "status": network.status.value,
                "trust_score": 0 if not network.verified else 50,
                "last_activity": network.last_activity.isoformat() if network.last_activity else None,
            }
            for network in self.list()
        ]

    def to_json(self) -> str:
        return json.dumps([network.as_dict() for network in self.list()], sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> "TrustedNetworkRegistry":
        payload = json.loads(value)
        networks = []
        for item in payload:
            for key in ("created_at", "verified_at", "last_activity"):
                if item.get(key):
                    item[key] = datetime.fromisoformat(item[key])
            networks.append(TrustedNetwork(**item))
        return cls(networks)

    @staticmethod
    def _replace(network: TrustedNetwork, **changes: Any) -> TrustedNetwork:
        return replace(network, **changes)


def assess_network(observation: NetworkObservation, registry: TrustedNetworkRegistry | None = None) -> RiskAssessment:
    """Combine threat, reputation, routing, behavior, and explicit trust.

    Risk inputs follow the documented limits: threat intelligence 0–50, IP
    reputation 0–30, ASN reputation 0–30, BGP anomalies 0–40, and behavior
    0–50.  Positive signals are represented as signed adjustments so the
    resulting score remains easy to explain to an operator.
    """
    negative = (
        _bounded(observation.threat_intelligence, 50)
        + _bounded(observation.ip_reputation, 30)
        + _bounded(observation.asn_reputation, 30)
        + _bounded(observation.bgp_anomalies, 40)
        + _bounded(observation.behavior, 50)
    )
    # Observable behavior flags are additive safeguards for compromised nodes.
    flags = sum((observation.mass_scans, observation.unusual_countries, observation.new_login_patterns))
    negative = min(100, negative + flags * 10)
    trust_adjustment = 0
    reasons: list[str] = []
    matched, node_match = registry.match(observation) if registry else (None, False)
    if matched:
        trust_adjustment -= 40
        reasons.append("verified trusted infrastructure")
        if node_match:
            trust_adjustment -= 10
            reasons.append("known node identity")
    if observation.rpki_status is RPKIStatus.VALID:
        trust_adjustment -= 20
        reasons.append("RPKI valid")
    elif observation.rpki_status is RPKIStatus.INVALID:
        negative = min(100, negative + 20)
        reasons.append("RPKI invalid")
    if observation.bgp_status is BGPStatus.STABLE:
        trust_adjustment -= 10
        reasons.append("stable BGP route")
    elif observation.bgp_status in (BGPStatus.CHANGED, BGPStatus.ANOMALOUS):
        negative = min(100, negative + (20 if observation.bgp_status is BGPStatus.ANOMALOUS else 10))
        reasons.append("BGP route changed")
    if observation.history > 0:
        trust_adjustment -= min(20, _bounded(observation.history, 20))
        reasons.append("established history")
    risk = max(0, min(100, negative + trust_adjustment))
    return RiskAssessment(
        risk_score=risk,
        trust_score=max(0, -trust_adjustment),
        negative_score=negative,
        trust_adjustment=trust_adjustment,
        trusted_network_id=matched.id if matched else None,
        trusted_network_name=matched.name if matched else None,
        matched_node=node_match,
        reasons=tuple(reasons),
    )


def network_intelligence(observation: NetworkObservation, assessment: RiskAssessment) -> dict[str, Any]:
    """Return the compact shape used by the Network Intelligence dashboard."""
    return {
        "ip": observation.ip,
        "asn": observation.asn,
        "provider": observation.provider,
        "prefix": observation.prefix,
        "bgp_status": observation.bgp_status.value,
        "rpki_status": observation.rpki_status.value,
        "risk": assessment.risk_score,
        "trust": assessment.trust_score,
        "trusted_network": assessment.trusted_network_name,
    }


__all__ = [
    "BGPStatus",
    "NetworkObservation",
    "NetworkType",
    "RPKIStatus",
    "RiskAssessment",
    "TrustedNetwork",
    "TrustedNetworkRegistry",
    "VerificationStatus",
    "assess_network",
    "network_intelligence",
]

from datetime import UTC, datetime, timedelta

from supermarkt.clawforge.intelligence import (
    ASNIntelligence,
    ASNNetworkType,
    ASNRecord,
    BGPIntelligence,
    BGPRoute,
    ThreatIndicator,
    ThreatProvider,
    builtin_providers,
    effective_indicator_confidence,
)
from supermarkt.clawforge.network_trust import (
    BGPStatus,
    NetworkObservation,
    RPKIStatus,
    TrustedNetworkRegistry,
    assess_network,
)
from supermarkt.clawforge.risk_engine import Decision, RiskEngine, RiskSignals


def test_unknown_overlay_network_is_neutral_but_verified_tailnet_gets_bonus():
    registry = TrustedNetworkRegistry()
    unknown = NetworkObservation(network_type="tailscale", identifier="tailnet-unknown", ip="100.64.0.4")
    assert assess_network(unknown, registry).trust_score == 0

    network = registry.register(name="Homelab Tailnet", type="tailscale", identifier="tailnet-1")
    assert assess_network(NetworkObservation(network_type="tailscale", identifier="tailnet-1"), registry).trust_score == 0
    registry.verify(network.id)
    result = assess_network(NetworkObservation(network_type="tailscale", identifier="tailnet-1"), registry)
    assert result.trust_score >= 40


def test_registered_ipv4_ipv6_vlan_and_compromised_node():
    registry = TrustedNetworkRegistry()
    network = registry.register(
        name="Server VLAN", type="vlan", networks=("192.168.10.0/24", "2001:db8:10::/64"), node_identities=("node-1",)
    )
    registry.verify(network.id)
    clean = assess_network(NetworkObservation(ip="2001:db8:10::9", node_identity="node-1", history=20), registry)
    compromised = assess_network(
        NetworkObservation(
            ip="192.168.10.9",
            node_identity="node-1",
            mass_scans=True,
            unusual_countries=True,
            threat_intelligence=40,
            rpki_status=RPKIStatus.INVALID,
        ),
        registry,
    )
    assert clean.risk_score < compromised.risk_score


def test_provider_errors_are_visible_and_sources_are_switchable():
    provider = ThreatProvider("test", "Test", "example", parser=lambda _payload: (_ for _ in ()).throw(ValueError("bad feed")))
    assert provider.parse("payload") == ()
    assert provider.error == "bad feed"
    provider.enabled = False
    assert provider.parse("payload") == ()
    assert {item.id for item in builtin_providers().all()} >= {"abusech-urlhaus", "spamhaus", "openphish"}


def test_asn_and_bgp_context_do_not_block_by_themselves():
    asns = ASNIntelligence([ASNRecord("AS64500", organisation="Lab", network_type=ASNNetworkType.ENTERPRISE, prefixes=("203.0.113.0/24",))])
    assert asns.for_ip("203.0.113.9").asn == "64500"
    bgp = BGPIntelligence([BGPRoute("203.0.113.0/24", "64500", stable_days=365)])
    assert bgp.assess("203.0.113.0/24", "64500")["stable"] is True


def test_rpki_invalid_and_bgp_change_raise_risk_even_for_trusted_network():
    registry = TrustedNetworkRegistry()
    network = registry.register(name="Own prefix", type="bgp", identifier="203.0.113.0/24")
    registry.verify(network.id)
    result = RiskEngine(registry).evaluate(
        NetworkObservation(
            ip="203.0.113.7",
            prefix="203.0.113.0/24",
            identifier="203.0.113.0/24",
            rpki_status=RPKIStatus.INVALID,
            bgp_status=BGPStatus.CHANGED,
            threat_intelligence=30,
        ),
        signals=RiskSignals(evidence_sources=frozenset({"bgp", "rpki"})),
    )
    assert result.risk.risk_score > 0
    assert result.policy.decision is not Decision.BLOCK


def test_stale_single_feed_cannot_auto_block():
    stale = ThreatIndicator(
        "198.51.100.9",
        "ip",
        confidence=100,
        source="one-feed",
        last_seen=datetime.now(UTC) - timedelta(days=365),
    )
    assert effective_indicator_confidence(stale) < 30
    result = RiskEngine().evaluate(NetworkObservation(), indicators=(stale,))
    assert result.policy.decision is not Decision.BLOCK

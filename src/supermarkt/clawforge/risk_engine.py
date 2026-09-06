"""Composite risk, trust, policy, and LLM-safe response layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .intelligence import ThreatIndicator, effective_indicator_confidence
from .network_trust import NetworkObservation, RiskAssessment, TrustedNetworkRegistry, assess_network


class Decision(StrEnum):
    OBSERVE = "observe"
    CHALLENGE = "challenge"
    RATE_LIMIT = "rate_limit"
    BLOCK = "block"


@dataclass(frozen=True)
class RiskSignals:
    threat_intelligence: int = 0
    ip_reputation: int = 0
    domain_reputation: int = 0
    asn_reputation: int = 0
    bgp_anomalies: int = 0
    behavior: int = 0
    history: int = 0
    evidence_sources: frozenset[str] = frozenset()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    risk_score: int
    corroborated: bool
    reasons: tuple[str, ...] = ()

    @property
    def may_block(self) -> bool:
        return self.decision is Decision.BLOCK


@dataclass(frozen=True)
class CompositeAssessment:
    risk: RiskAssessment
    signals: RiskSignals
    policy: PolicyDecision

    def llm_context(self) -> dict[str, object]:
        """Only reviewed, aggregate information is exposed to an LLM."""
        return {
            "risk_score": self.risk.risk_score,
            "trust_score": self.risk.trust_score,
            "decision": self.policy.decision.value,
            "corroborated": self.policy.corroborated,
            "trusted_network": self.risk.trusted_network_name,
            "reasons": list(dict.fromkeys((*self.signals.reasons, *self.risk.reasons, *self.policy.reasons))),
        }


class PolicyEngine:
    """Map composite scores to actions while requiring corroboration to block."""

    def decide(self, risk_score: int, evidence_sources: Iterable[str], reasons: Iterable[str] = ()) -> PolicyDecision:
        sources = frozenset(source for source in evidence_sources if source)
        score = max(0, min(100, int(risk_score)))
        if score < 40:
            decision = Decision.OBSERVE
        elif score < 70:
            decision = Decision.CHALLENGE
        elif score < 90:
            decision = Decision.RATE_LIMIT
        else:
            decision = Decision.BLOCK if len(sources) >= 2 else Decision.RATE_LIMIT
        decision_reasons = list(reasons)
        if score >= 90 and len(sources) < 2:
            decision_reasons.append("block requires corroborating independent signals")
        return PolicyDecision(decision, score, len(sources) >= 2, tuple(dict.fromkeys(decision_reasons)))


class RiskEngine:
    def __init__(self, registry: TrustedNetworkRegistry | None = None, policy: PolicyEngine | None = None) -> None:
        self.registry = registry or TrustedNetworkRegistry()
        self.policy = policy or PolicyEngine()

    def evaluate(
        self,
        observation: NetworkObservation,
        *,
        indicators: Iterable[ThreatIndicator] = (),
        signals: RiskSignals | None = None,
    ) -> CompositeAssessment:
        indicators = tuple(indicators)
        feed_sources = frozenset(indicator.source for indicator in indicators if indicator.source)
        threat = max((effective_indicator_confidence(item) for item in indicators), default=0)
        # Multiple independent reports raise confidence, capped at the defined range.
        if len(feed_sources) > 1:
            threat = min(50, threat + min(20, (len(feed_sources) - 1) * 10))
        supplied = signals or RiskSignals()
        merged = RiskSignals(
            threat_intelligence=max(threat, supplied.threat_intelligence, observation.threat_intelligence),
            ip_reputation=max(0, min(30, max(supplied.ip_reputation, observation.ip_reputation))),
            domain_reputation=max(0, min(30, supplied.domain_reputation)),
            asn_reputation=max(0, min(30, max(supplied.asn_reputation, observation.asn_reputation))),
            bgp_anomalies=max(0, min(40, max(supplied.bgp_anomalies, observation.bgp_anomalies))),
            behavior=max(0, min(50, max(supplied.behavior, observation.behavior))),
            history=max(0, min(20, supplied.history)),
            evidence_sources=frozenset((*feed_sources, *supplied.evidence_sources)),
            reasons=supplied.reasons,
        )
        # The network layer supplies its own bounded reputation and trust inputs.
        network_observation = NetworkObservation(
            **{
                **observation.__dict__,
                "threat_intelligence": merged.threat_intelligence,
                "ip_reputation": merged.ip_reputation,
                "asn_reputation": merged.asn_reputation,
                "bgp_anomalies": merged.bgp_anomalies,
                "behavior": merged.behavior,
            }
        )
        network_risk = assess_network(network_observation, self.registry)
        risk_value = min(100, max(0, network_risk.risk_score + merged.domain_reputation + merged.history))
        reasons = list(merged.reasons)
        if merged.domain_reputation:
            reasons.append("domain or URL reputation")
        if merged.history:
            reasons.append("negative activity history")
        policy = self.policy.decide(risk_value, merged.evidence_sources, reasons)
        risk = RiskAssessment(
            risk_score=risk_value,
            trust_score=network_risk.trust_score,
            negative_score=network_risk.negative_score + merged.domain_reputation + merged.history,
            trust_adjustment=network_risk.trust_adjustment,
            trusted_network_id=network_risk.trusted_network_id,
            trusted_network_name=network_risk.trusted_network_name,
            matched_node=network_risk.matched_node,
            reasons=network_risk.reasons,
        )
        return CompositeAssessment(risk=risk, signals=merged, policy=policy)


__all__ = [
    "CompositeAssessment",
    "Decision",
    "PolicyDecision",
    "PolicyEngine",
    "RiskEngine",
    "RiskSignals",
]

# Risk- und Trust-Engine

Die Architektur ist modular:

```text
Datenquellen -> Provider Layer -> Normalizer -> Risk + Trust Engine
             -> Policy Engine -> Response Layer
```

Die Engine kombiniert Threat Intelligence (0–50), IP-Reputation (0–30),
Domain-/URL-Reputation (0–30), ASN-Reputation (0–30), BGP-Anomalien (0–40),
Verhalten (0–50) und negative Historie (0–20). Positive Anpassungen sind
verifizierte Infrastruktur (-50 bis 0), RPKI/BGP-Vertrauen (-30 bis 0) und
Netzwerkhistorie (-20 bis 0). Der resultierende Risk Score wird auf 0–100
begrenzt; der Trust Score beschreibt die positiven Anpassungen separat.

Schwellenwerte:

* 0–40: beobachten
* 40–70: Challenge/Anubis
* 70–90: Rate Limit oder zusätzliche Prüfung
* 90–100: Block nur nach Policy

Die Policy Engine verlangt für einen Block mindestens zwei unabhängige
Evidenzquellen. Ein einzelner Feed, ein ASN, eine BGP-Änderung oder ein
RPKI-Status kann daher niemals automatisch blockieren. Provider-Fehler führen
zu einem sichtbaren Fehlerstatus und nicht zu einem stillen Vertrauensbonus.

Die Feed-Synchronisation schreibt Providerstatus und normalisierte Daten in die
SQLite-Tabellen `providers`, `provider_status`, `indicators`, `asn_records`,
`bgp_events`, `risk_history`, `trust_history` und `audit_events`. Der
`IntelligenceConsumer` bewertet neue Indicators unmittelbar nach dem Store-
Commit. Jede Bewertung speichert Indicator, Quelle, Score-Änderung, Grund und
Zeitpunkt in `risk_history`; positive Trust-Signale werden zusätzlich in
`trust_history` festgehalten. Mehrere unterschiedliche Quellen für denselben
Indicator werden als korroboriertes Signal an die Engine übergeben.

Das Schema wird über `schema_migrations` und den `MigrationRunner` versioniert.
`SQLiteBackend` ist die aktuelle Implementierung der kleinen
`DatabaseBackend`-Schnittstelle; ein PostgreSQL-Backend kann später dieselbe
Repository-Grenze verwenden.

## LLM-Grenze

Ein LLM erhält nur die bereits bewertete Zusammenfassung: Risk Score, Trust
Score, Entscheidung und Begründungen. Rohfeeds werden nicht weitergereicht.
Das LLM darf erklären und Reports formulieren, aber weder blockieren,
Policies ändern noch Provider aktivieren.

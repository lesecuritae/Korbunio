# Trusted Infrastructure

Vertrauen entsteht ausschließlich durch eine explizite Administrator-
Registrierung. Die Verwendung von Tailscale, NetBird, VLAN, WireGuard,
OpenVPN, privaten IPs oder einem ASN erzeugt keinen Trust.

`TrustedNetworkRegistry.register()` legt zunächst einen Eintrag mit Status
`pending` an. Erst `verify(network_id)` oder eine Registrierung mit
`admin_confirmed=True` setzt den Status auf `verified`. Nur verifizierte
Einträge können eine Beobachtung matchen. Unterstützt werden Tailnets und
Nodes, NetBird-Netzwerke und Peers, VLAN-Netze, VPN-Tunnel, IPv4-/IPv6-
Bereiche sowie eigene ASNs und BGP-Prefixe.

Ein Match über das registrierte Netzwerk gibt bis zu 40 Punkte Trust-Bonus.
Eine bekannte Node-Identität kann weitere 10 Punkte geben. RPKI `VALID`, eine
stabile Route und eine lange Historie werden separat bewertet. Unbekannte
Tailscale- oder NetBird-Netze bleiben neutral.

Trust ist kein Freifahrtschein. Threat Intelligence, IP-/ASN-Reputation,
Verhalten, BGP-Anomalien und RPKI `INVALID` werden weiterhin eingerechnet.
Massenscans, ungewöhnliche Länder oder neue Login-Muster können das Risiko
eines eigenen Nodes deshalb erhöhen. Registrierungen sollten bei einem
Incident widerrufen werden (`revoke`).

Die Dashboard-Ansicht zeigt Name, Typ, Identifier, Netzbereiche, Status,
Trust-Bonus und letzte Aktivität. Export und Import erfolgen über die
JSON-Methoden des Registers; vor der Speicherung sollten Betreiber die Daten
verschlüsseln und Änderungen auditieren.

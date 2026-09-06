# Network Intelligence

Die Network-Intelligence-Schicht verbindet IP-Kontext, ASN, Provider,
Prefix-Historie, BGP-Routen und RPKI. Sie liefert Fakten und bounded scores an
die Risk Engine; sie entscheidet nicht selbst über eine Sperre.

`ASNRecord` enthält ASN, Organisation, Provider, Land, Prefixe, Netzwerktyp und
Reputation. Die Klassifizierung unterscheidet Residential ISP, Enterprise,
Cloud, VPN, Hosting, Bulletproof Hosting, Tor Exit und unbekannt. Der
Netzwerktyp ist ein Kontextsignal: Auch ein Cloud-, VPN- oder Tor-ASN darf
alleine keine Aktion auslösen.

`BGPIntelligence` vergleicht bekannte Prefixe und Origin-ASNs. Ein unbekannter
Prefix, ein ASN-Wechsel oder eine instabile Route werden als Anomalie markiert;
eine lange stabile Historie wird als positives Signal verwendet. RPKI ist
dreistufig: `VALID` gibt einen Bonus, `UNKNOWN` bleibt neutral, `INVALID`
erhöht das Risiko auch bei einer registrierten eigenen Infrastruktur.

Dashboard-Daten enthalten IP, ASN, Provider, Prefix, BGP- und RPKI-Status sowie
die bereits berechneten Risk- und Trust-Werte. Rohdaten bleiben im
Intelligence-Layer.

Die Synchronisationsschicht persistiert ASN-Daten in `asn_records` und
Routing-Ereignisse in `bgp_events`. Die Adapter sind für RIPEstat, BGPView,
RIPE RIS, RouteViews, BGPStream, CAIDA, RPKI, Team Cymru, PeeringDB und
Spamhaus ASN Reputation registriert. Provider-spezifische Endpunkte und
Zugangsdaten bleiben konfigurierbar; Datenquellen werden nicht als direkte
Blockierentscheidung verwendet.

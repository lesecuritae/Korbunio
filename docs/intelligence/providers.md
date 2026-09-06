# Threat-Intelligence-Provider

Clawforge behandelt Feeds als austauschbare Datenquellen. Ein Provider hat eine
stabile ID, einen Namen, die Quellorganisation, ein Aktualisierungsintervall,
Parser und Normalizer, einen Konfidenzwert, Kategorien, Datenalter und einen
Fehlerstatus. Provider werden einzeln aktiviert oder deaktiviert; ein Fehler in
einem Feed darf die übrigen Signale nicht ausblenden.

`clawforge.intelligence.builtin_providers()` liefert die Metadaten für URLhaus,
ThreatFox, Feodo Tracker, MalwareBazaar, Spamhaus, OpenPhish, PhishTank,
DShield/SANS ISC, Blocklist.de, FireHOL, Emerging Threats Open, GreyNoise
Community sowie optional VirusTotal, CISA KEV, NVD und EPSS. Der Abruf selbst
bleibt bei einem Adapter der Anwendung, damit Zugangsdaten, Rate Limits und
Caching pro Quelle kontrolliert werden können.

Parser geben normalisierte `ThreatIndicator`-Objekte für IPs, Domains, URLs,
Hashes oder ASNs zurück. Werte werden kanonisiert und alte Meldungen verlieren
Konfidenz. Ein einzelner Treffer erzeugt damit ein Signal, aber keine
automatische Sperre.

## Synchronisation

`clawforge.feed_sync` ergänzt die Provider um einen zentralen
`FeedScheduler`. Jeder Provider besitzt ein eigenes Intervall, einen Timeout
und einen Rate-Limit-Abstand. Fehler werden mit exponentiellem Backoff erneut
versucht; ein Provider-Ausfall stoppt keine anderen Quellen. Der Scheduler
speichert Status, letzte erfolgreiche Synchronisation, nächste Ausführung,
Fehler und Trefferanzahl.

Die erste Adaptergruppe umfasst URLhaus, ThreatFox, Feodo Tracker,
MalwareBazaar, Spamhaus DROP/EDROP, Blocklist.de, DShield, FireHOL,
OpenPhish, PhishTank, GreyNoise, Emerging Threats, CISA KEV und NVD. ASN-,
BGP- und RPKI-Adapter schreiben in eigene Tabellen. abuse.ch APIs werden über
`CLAWFORGE_ABUSECH_AUTH_KEY` authentifiziert; öffentliche Quellen werden mit
ihren konfigurierten Rate-Limits abgerufen.

Die Synchronisation wird über `CLAWFORGE_INTELLIGENCE_AUTOSTART=1` beim
Anwendungsstart aktiviert. Ohne Aktivierung bleiben Adapter und Datenbank
verfügbar, aber es werden keine externen Feeds abgerufen.

Für den getrennten Betrieb startet `python -m supermarkt.intelligence_worker`
den Scheduler als eigenen Prozess. Compose verwendet diesen Worker neben dem
API-Service; die Runtime-Konfiguration und Backend-Auswahl sind in
`docs/intelligence/runtime.md` beschrieben.

Jeder Indicator speichert `first_seen`, `last_seen` und `expires_at`. Gleiche
Werte werden pro Provider und Indicator-Typ dedupliziert. Abgelaufene Werte
werden vor der weiteren Bewertung entfernt.

Nach dem Store-Commit übernimmt `IntelligenceConsumer` die Bewertung über die
Risk Engine und schreibt ein begründetes Ereignis in `risk_history`. Mehrere
Quellen für denselben Wert werden gemeinsam als korroboriertes Signal bewertet;
der Consumer löst selbst keine Blockierung aus.

## Lizenzen und Datenschutz

Vor der Aktivierung sind Nutzungsbedingungen, Redistribuierung, API-Limits und
Attribution der jeweiligen Quelle zu prüfen. Rohfeeds sollten nur so lange wie
nötig gespeichert werden. Für die Bewertung genügen normalerweise IOC-Typ,
Wert, Quelle, Konfidenz und Zeitstempel; lokale Identitäten und vollständige
Anfrageprotokolle gehören nicht in einen externen Feed.

## Interne Status-APIs

Bei konfigurierter API-Authentifizierung sind folgende interne Endpunkte
verfügbar:

- `/intelligence/providers` — Provider, Aktivierung, letzter Lauf, Fehler und Treffer
- `/intelligence/status` — Schedulerstatus, Backoff und nächste Ausführung
- `/intelligence/indicators` — normalisierte, nicht abgelaufene Indicators
- `/network/asn` — gespeicherte ASN-Datensätze
- `/network/bgp` — gespeicherte Routing-Ereignisse
- `/network/trust` — registrierte Trusted Networks

Die Endpunkte liefern Daten zur Bewertung. Sie lösen keine Blockierung aus.

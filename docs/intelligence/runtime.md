# Intelligence Runtime und Persistenz

Der API-Prozess startet den Intelligence Scheduler nicht automatisch. Die
Umgebungsvariable `CLAWFORGE_INTELLIGENCE_AUTOSTART` bleibt für einen
Einprozessbetrieb verfügbar, ist im Compose-API-Service aber deaktiviert.

Der separate `intelligence-worker` startet
`supermarkt.intelligence_worker`. Er besitzt den Feed-Scheduler, führt Sync-Jobs
aus, übergibt neue Daten an den Risk Consumer und schreibt Providerfehler in
`provider_status` und `audit_events`. Feed-Daten lösen keine Blockierung aus.

Compose stellt drei Services bereit:

- `api` für HTTP/API und Dashboard-Routen
- `intelligence-worker` für Scheduler und Sync-Jobs
- `postgres` als optionale produktive Persistenz

SQLite bleibt mit `CLAWFORGE_INTELLIGENCE_BACKEND=sqlite` das lokale Test- und
Fallback-Backend. Für PostgreSQL werden `CLAWFORGE_INTELLIGENCE_BACKEND=postgres`
und ein `CLAWFORGE_POSTGRES_DSN` gesetzt. Das optionale Python-Extra
`postgres` installiert den psycopg-Treiber.

Das Schema wird über `schema_migrations` versioniert. Die Migrationen enthalten
Providerstatus, Indicators, ASN-Records, BGP-Historie, Risk-/Trust-Historie und
Audit-Events. `DatabaseBackend` trennt den Store vom konkreten Treiber.

## Backup und Restore

`BackupManager` erstellt ein operator-initiiertes Backupverzeichnis mit
Datenbankdump, ausdrücklich ausgewählten Konfigurationsdateien, ausdrücklich
ausgewählten Secret-Dateien und optionaler Trust-Registry. Secrets werden mit
restriktiven Dateirechten abgelegt und nicht automatisch gesucht. SQLite wird
über den konsistenten SQLite-Backup-Mechanismus kopiert; PostgreSQL verwendet
`pg_dump`/`pg_restore`.

Trust-Registrierungen werden als JSON exportiert und müssen nach einem Restore
gezielt wieder in den Runtime-Service geladen werden. Ein Backup verändert
keine Policy und aktiviert keinen Provider.

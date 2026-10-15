# Einkaufen und Angebote beobachten

Die Oberfläche ist derzeit deutsch. Diese Anleitung beschreibt die für #58 vorbereiteten Änderungen. Der Stand ist noch keine veröffentlichte Version und keine Geräteabnahme.

## Einkaufsliste

Im Tab **Einkaufen** lässt sich die Liste bis zum letzten Eintrag scrollen. Positionen sind nach Händler gruppiert; ohne Händler erscheinen sie in einer eigenen Gruppe. Ein Eintrag enthält Produkt, Packung, Menge, bekannten Angebots- und Grundpreis sowie seine Preisbedingungen. Gleiche Produkte aus verschiedenen Händlerangeboten bleiben als eigene Positionen erhalten.

Ändere die Menge an der jeweiligen Position. Fehlende Preise bleiben unbekannt; die angezeigte bekannte Teilsumme schließt diese Positionen nicht als kostenlose Artikel ein. Pfand und Warenwert werden getrennt ausgewiesen. Ein gespeichertes Angebot kann abgelaufen sein; seine Gültigkeit und sein Preisstand helfen, das zu erkennen. Prüfe den aktuellen Preis beim Händler.

Der JSON-Export dient zum verlustarmen Sichern und Übertragen der Liste. Der Text-Export ist für das Teilen oder Ausdrucken gedacht. Prüfe beim Text-Import die Vorschau mit erkannten Positionen, übersprungenen Zeilen und Fehlern. Ein freier Text kann nicht alle strukturierten Angebotsdaten enthalten. Ein vollständiges App-Backup ist eine eigene Funktion; Zugangsdaten für ntfy werden nicht in Listen oder Backups exportiert und müssen auf einem neuen Gerät erneut eingetragen werden.

## Mehrkauf richtig lesen

**„3 Stück für insgesamt 3,00 €“ verlangt drei Packungen.** Der dabei angegebene Stückpreis von 1,00 € gilt nur für diesen Mehrkauf. Ohne belegten Einzelpreis lässt sich daraus kein Preis für eine oder zwei Packungen ableiten.

| Einkaufsmenge | Bekannter Preis bei 3 für 3 € ohne bekannten Einzelpreis |
| --- | --- |
| 1 oder 2 | unbekannt |
| 3 | 3,00 € |
| 4 | ein Bündel für 3,00 €; Preis der vierten Packung unbekannt |
| 6 | 6,00 € |

Packungsgröße und Bündelmenge sind verschieden: „je 80-g-Packg.“ beschreibt eine Packung; „4 Stück für 4,00 €“ vier solche Packungen. Ein Grundpreis mit „nur Mehrkauf“ gehört zur Preisbedingung. Verschiedene Sorten oder Produkte werden nur zu einer Mischaktion zusammengefasst, wenn die Quelle diese Kombination ausdrücklich belegt. Eine gemeinsame interne Aktionskennung reicht dafür nicht aus.

`Em-eukal`, `EmEukal` und `Emeukal` werden als Schreibweisen desselben Suchbegriffs erkannt. Andere Bonbonmarken werden dadurch nicht als Ersatztreffer hinzugefügt. Das Rechenbeispiel „3 für 3 €“ ist kein Nachweis eines aktuell verfügbaren Em-eukal-Angebots; siehe [datierte Quellenprüfung](kaufland-mehrkauf-quellen-20261015.md).

## Favoriten und optionale ntfy-Meldungen in der Android-App

Speichere einen Suchbegriff als Favorit und wähle die gewünschten Händler sowie aktuelle und/oder folgende Woche. Ein leerer Händlerfilter bedeutet alle unterstützten Händler. Die Postleitzahl bestimmt den regionalen Angebotsbestand. Ein Höchstpreis bezieht sich auf den an der Kasse zu zahlenden Angebotsbetrag; Guthaben oder späteres Cashback senken diese Grenze nicht. Bei einer Mehrkaufaktion ist der Angebotsbetrag der Preis des ganzen Bündels.

Für Meldungen ist zusätzlich eine aktivierte ntfy-Verbindung erforderlich:

1. Wähle ein Thema auf einem öffentlichen oder selbst betriebenen ntfy-Server und abonniere dasselbe Thema in deinem ntfy-Empfänger.
2. Trage die vollständige HTTPS-Themenadresse ein, beispielsweise `https://ntfy.example/mein-thema`. Falls der gewählte Server eine Anmeldung verlangt, trage den Bearer-Token in das dafür vorgesehene Feld ein.
3. Aktiviere die Verbindung und sende eine Testnachricht. Eine erfolgreiche Übermittlung bestätigt, dass der Server den POST angenommen hat; prüfe zusätzlich, dass die Nachricht im Empfänger ankommt.
4. Aktualisiere die Angebote. Für regelmäßige Prüfungen muss auch die optionale Hintergrundaktualisierung eingerichtet sein. Das Speichern einer ntfy-Verbindung aktiviert sie nicht automatisch.

Dafür ist kein zentraler Korbuino-Account erforderlich. Themenadresse und Token werden als Zugangsdaten behandelt. Gib sie nicht in geteilten Listen oder Fehlerberichten an. Bei einem öffentlichen Thema richtet sich der Lese- und Schreibzugriff nach den Regeln des gewählten ntfy-Servers.

Meldungen entstehen nach erfolgreichen Angebotsaktualisierungen. Android kann Hintergrundarbeit verzögern; dies ist kein Dienst mit garantierter Zustellzeit. Fehlgeschlagene Übermittlungen werden nicht als erfolgreiche Meldung gespeichert. Ein bereits gemeldetes Angebot wird beim Übergang von der Vorschau in die aktuelle Woche anhand seiner echten Gültigkeit wiedererkannt.

Eine Folgewoche erscheint nur, wenn die Quelle eine echte Vorschau mit passenden Daten veröffentlicht. Ein aktueller REWE-Katalog auf einer `week=next`-Adresse wird nicht umdatiert. Ohne Vorschau gibt es keine erfundene zukünftige Aktion.

## Beobachtungen auf dem eigenen Korbuino-Server

Richte auf `/settings` eine ntfy-Themenadresse oder einen POST-Webhook ein. Danach stehen im MCP-Client `watch_product`, `list_watches` und `remove_watch` zur Verfügung. Bis zu 20 Beobachtungen sind möglich. Der Server prüft standardmäßig einmal täglich; ein ausgefallener Server kann keine Meldung senden.

Beispiel für ein MCP-Werkzeugargument:

```json
{
  "product": "Cola",
  "max_price": "3,00",
  "postal_code": "78464",
  "retailer_ids": ["rewe", "lidl", "kaufland"],
  "offer_week": "all"
}
```

`offer_week` ist `current`, `next` oder `all`; der Standard und migrierte alte Beobachtungen verwenden `current`. Händler-IDs sind unabhängig vom Anzeigenamen. `list_watches` zeigt die gespeicherten Filter. Der Server sendet Treffer in kleinen Nachrichtenpaketen und merkt nur erfolgreich übermittelte Pakete vor; nach einem Fehler bleiben die übrigen Treffer für einen späteren Versuch offen.

Die Android-App und der optionale Server verwalten ihre Beobachtungen und ntfy-Zugangsdaten jeweils selbst. Prüfe beide Konfigurationen, wenn du beide Wege gleichzeitig verwendest.

# Kaufland: datierte Quellenprüfung zum Mehrkauf

Geprüft am **15. Oktober 2026** anhand öffentlicher Kaufland-Daten. Die Abrufe belegen den damals ausgelieferten Datenstand, keinen heutigen Kassenbestand und keine nachträgliche Rekonstruktion älterer Aktionen.

## Konstanz und öffentliche Filialauswahl

| Filiale | Filialkennung | PLZ | Offizielle Filialseite |
| --- | --- | --- | --- |
| Konstanz-Petershausen | DE5220 | 78464 | https://filiale.kaufland.de/service/filiale/konstanz-petershausen-5220.html |
| Konstanz-Industriegebiet | DE1680 | 78467 | https://filiale.kaufland.de/service/filiale/konstanz-industriegebiet-1680.html |

Die Angebotsseite wurde für jede Filiale separat mit der öffentlichen Filialauswahl `x-aem-variant=DE5220` beziehungsweise `DE1680` abgefragt. Regionale Verfügbarkeit kommt zusätzlich aus `.kloffers.storeName=<Kennung>.json`. Ein Abruf der allgemeinen Übersicht ohne Filialauswahl ist kein Nachweis für einen Konstanzer Preis.

Verbatim übernommene ausgewählte Angebotsobjekte und zugehörige Verfügbarkeitsdatensätze liegen in:

- [DE5220: Angebote und Verfügbarkeit](../tests/fixtures/kaufland/DE5220-20261015-bundles.json), [Provenienz](../tests/fixtures/kaufland/DE5220-20261015-provenance.json).
- [DE1680: Angebote und Verfügbarkeit](../tests/fixtures/kaufland/DE1680-20261015-bundles.json), [Provenienz](../tests/fixtures/kaufland/DE1680-20261015-provenance.json).

Die Provenienzdateien enthalten genaue Abrufzeit, öffentliche URL, HTTP-Status und SHA-256 der vollständigen Ausgangsantworten sowie den Hash des eingecheckten Ausschnitts. Die Ausschnitte enthalten keine erfundenen Produkt- oder Preisfelder. In den Tests zusätzlich erzeugte Katalogauffüllungen sind ausdrücklich synthetisch und keine Quelldaten.

## Tatsächlich gefundene Mehrkaufaktionen

In beiden Konstanzer Antworten stehen unter anderem:

| Produkt | Quelldaten | Gesicherte Bedeutung |
| --- | --- | --- |
| SNACK IT Salamistangen | `price=4`, `bbyMessage=["4 Stück", "entspr. pro Packg. 1.00"]`, `unit="je 80-g-Packg."` | Vier Packungen zusammen 4,00 €; 1,00 € je Packung nur im Mehrkauf |
| K-CLASSIC Emmentaler | `price=5`, `bbyMessage=["2 Stück", "entspr. pro Packg. 2.50"]` | Zwei Packungen zusammen 5,00 € |
| K-WINTER EDITION Adventskalender | `bbyMessage=["3 Stück", "entspr. pro Stück 1.00"]`, `price=3` | Drei Stück zusammen 3,00 € |

Die Aktions-IDs unterscheiden sich regional: zum Beispiel `ART.882910_KAV.3693303` in DE5220 und `ART.882910_KAV.3692743` in DE1680. Die Filialzuordnung wird nicht durch Produktähnlichkeit ersetzt.

`bonusbuy=true` tritt auch bei gewöhnlichen Kundenkartenpreisen ohne Mengenaktion auf. Es genügt nicht als Mehrkauferkennung. Auch `bbyNo` belegt keine erlaubte Mischung verschiedener Produkte. Der Parser verwendet die ausdrücklich in `bbyMessage` genannte Stückzahl und den Bündelgesamtpreis. Ein unbekannter Einzelpreis bleibt unbekannt. Nicht verstandene Aktionsbedingungen bleiben sichtbar und werden vom gewöhnlichen Preisvergleich ausgeschlossen.

Die reale Gültigkeit folgt aus der Schnittmenge von `dateFrom/dateTo`, gegebenenfalls engeren `salesFrom/salesTo` und der regionalen Verfügbarkeit. Bei den geprüften Wochenstartaktionen beginnt der tatsächliche Verkauf am 12.10.2026, obwohl das äußere Datumsfeld am 11.10.2026 beginnt. Die Auswahl „aktuelle/folgende Woche“ verändert diese Quelldaten nicht.

## Offene historische Em-eukal-Lücke

Das gemeldete **Em-eukal-Angebot „3 für 3 €“ in Konstanz für 08.–14.10.2026 konnte nicht aus einer authentischen historischen Antwort rekonstruiert werden**. Die am 15.10.2026 aufgenommenen Filial-, Verfügbarkeits- und Angebotsantworten für DE5220, DE1680 und zusätzlich Guben DE4620 enthalten kein Em-eukal-Angebot. Guben ist ein anderer Markt und wäre ohnehin kein regionaler Nachweis für Konstanz.

Die allgemeine Fehlerklasse ist durch die echten aktuellen Konstanzer Mengenaktionen belegt und getestet. Die Em-eukal-Schreibweisen und die Rechnung „3 für 3 €“ werden zusätzlich in klar bezeichneten synthetischen Tests geprüft. Diese Tests ersetzen weder die historische Quelldatei noch eine Prüfung der damaligen Konstanzer Verfügbarkeit. Es wurde kein historisches Em-eukal-Objekt erfunden oder aus einem anderen Markt als Konstanzer Beleg ausgegeben.


## Nutzerklärung

Am 15.10.2026 stellte der Nutzer klar, dass Em-eukal die Aktion der Vorwoche
war, und beendete den Auftrag zur weiteren historischen Prospektsuche.
Der Fehler wird deshalb nicht als aktuell fehlendes Konstanzer Angebot ausgegeben.
Die allgemeine Mengenpreisbehandlung bleibt durch echte Konstanzer Quelldaten
abgedeckt. Weder API-Abwesenheit noch ein aktueller Prospekt beweisen, dass die
historische Aktion nicht existierte.

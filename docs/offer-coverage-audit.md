# Händler-Angebotsabdeckung

Stand: 10.11.2026. Ausgangsrevision: `1479643ff66bc54184ff9cdca27b5f1247ce2635`
(0.1.75). **Arbeitsstand, keine vollständige Abnahme und kein Release.**

## Verfahren und Aussagegrenzen

Das Backend registriert 19 Händler. Android besitzt 18 eigenständige native
Provider; Marktkauf ist bisher über den Server erreichbar. Die vollständige
Stichprobenliste steht in [offer-coverage-samples.json](offer-coverage-samples.json):
100 historische Beobachtungen für alle 19 Händler, darunter ausdrücklich
unverifizierte Regionen und Gegenproben regulärer Müller-Artikel. Diese Daten
werden niemals als Angebote in die Anwendung importiert.

`verified` bezieht sich nur auf den beschriebenen Belegumfang. Eine bestätigte
Online-Produktseite beweist weder einen Aktionspreis noch Filialbestand. Eine
Prospektabbildung belegt keine strukturierte API-Variante. Produktnamen aus
unterschiedlichen Quellen sind nicht automatisch identisch. Preise für App,
Mehrkauf und Pfand werden separat behandelt. Eine gefüllte Liste beweist keine
vollständige Prospektabdeckung.

Live-Prüfungen fanden in 04109 Leipzig, 50939 Köln, 10115 Berlin und 26135
Oldenburg statt. 26122 wurde zusätzlich negativ geprüft: Eine fehlende Filiale
in genau dieser PLZ ist kein Parserfehler. Auch ein Oldenburger Prospekt ist
keine bundesweite Stichprobe. Live-Rohantworten, Bilder und Betriebsprotokolle
werden nicht eingecheckt.

## Lidl: belegte Datenkette und Grenzen

Marktguru lieferte für Leipzig/Köln 831/919 Rohdatensätze zu `q=Lidl`.
Kania Wildgerichte, 400 g, 3,99 €, ID 25583947 steht erst an Position 267/237.
Die UTC-Zeiten 08.11. 23:00 bis 14.11. 22:59:59 ergeben in Berlin 09.–14.11.
Die öffentliche Markenseite nennt dagegen den 08.11.; diese Darstellungen
werden nicht künstlich gleichgesetzt. `q=Konserven` findet den Datensatz,
`q=Gulasch` nicht.

Ein vollständiger regionaler Abruf reproduzierte einen konkreten Verlust:
Konserven- und gezielte Lidl-Anfragen liefen in Timeouts, während andere
Anfragen 321 Lidl-Angebote lieferten. Kania fehlte in diesem gefüllten Katalog.
Ein späterer erfolgreicher Abruf des produktiven 0.1.75-Dockers fand den
generischen Artikel bereits; der frühere Cachezustand ist damit nicht bewiesen.

Die regional verknüpften KaufDA-Viewer 2501324792 (Leipzig) und 2501324797
(Köln) liefern Kania Wildschwein, 400 g, 3,99 €, 09.–14.11. Die Ergänzung läuft
auch bei gefüllter Primärquelle. Keine landesweite Ersatzregion wird angenommen;
Herausgeber, Ortslink und tatsächliche Koordinaten werden geprüft. Die
Quellkategorie „Wildschweingulasch“ ergänzt nur den dazu passenden Produkttitel.
Sie wird nicht zu einer Hirsch- oder allgemeinen Wildfleisch-Synonymregel.

Die inzwischen unabhängig betrachtete deutsche Lidl-Prospektseite, Druckkennung
LHZ46/2026–DE, zeigt **Wildschwein- und Hirsch-Gulasch** bei Kania Wildgerichte.
[Prospektabbildung](https://content-media.bonial.biz/1396aa16-e502-49fd-af3b-975009900964/zoomlarge_page_10.jpg?impolicy=zoomlarge).
Damit ist die frühere Vermutung „Hirsch unbestätigt“ überholt. Die untersuchten
strukturierten Datensätze nennen Hirsch weiterhin nicht. Es wird kein
hartcodierter Hirsch-Datensatz aus der Abbildung erzeugt; diese Variantenlücke
bleibt `UPSTREAM_MISSING`.

Im isolierten Test-Docker lieferten reale API-/MCP-Aufrufe am 10.11.:
801 Lidl-Artikel, Wildgerichte 1 Treffer, Wildschwein 1 Treffer,
Wildschweingulasch 1 Treffer, Hirschgulasch 0 Treffer. Die API zeigte den
Ortsprospekt-Hinweis, MCP den konservativen Status `partial`. Kein Anspruch auf
Filialbestand oder vollständigen Prospekt. Mayonnaise aus der fixierten
09.11.-Fixture war am 10.11. abgelaufen und wurde im Live-Test nicht künstlich
verlängert. Die deterministischen API-/MCP-Tests prüfen die veröffentlichten
Normal-/Lidl-Plus-Paare 1,69/1,29 € und 1,79/1,39 €.

## Müller: Kategorien waren kein Angebotsnachweis

Der bestehende produktive Abruf erfasste nur Seite 1 von vier Abteilungen
(237 Artikel). Bei der Erweiterung der Seitennavigation wurden zunächst
17.273 Produktkarten aus neun Abteilungen gelesen. **Diese Zahl war keine
Angebotszahl.** Die Aktionen-Kategorien enthalten auch reguläres Sortiment:
Auf der erfassten Drogerie-Seite waren nur 24 von 60 Karten als Sale markiert.

Ein unabhängiger Produktseitenabgleich der ersten fünf Karten zeigte:

| Produkt | Onlinepreis | Ausdrücklicher Sale-Beleg |
|---|---:|---|
| fashy Wärmflasche 2 l mit Fleecebezug | 8,99 € | ja |
| fashy Wärmflasche 2 l mit Flauschbezug | 19,99 € | nein |
| fashy Wärmflasche 2 l Halblamelle | 6,99 € | ja |
| Gillette MACH3 Rasierklingen | 14,95 € | nein |
| L’Oréal Men Expert Invincible Sport | 2,35 € | ja |

Die Korrektur in Backend und Android verlangt Müllers ausdrückliche
Sale-Kennzeichnung. Kategorie, „Neu“, Eigenmarke, Multipack und ein UVP-Vergleich
allein reichen nicht. Die Navigation prüft die IDs aller lesbaren Produktkarten,
getrennt vom Angebotsfilter: Eine reguläre Seite darf Angebote auf späteren
Seiten nicht verdecken. Fehlende/wiederholte Seiten bleiben sichtbar unvollständig.

Der vollständige Abruf aller Produktkarten dauerte knapp zehn Minuten.
Das ist eine gemessene Grenze des kalten Abrufs, keine zugesicherte Antwortzeit.
Der Backend-Katalog wird für weitere PLZ wiederverwendet. Der erneute Abruf derselben neun Kategorien las 294 Seiten und übernahm
**2.816 ausdrücklich als Sale markierte Artikel**, ohne gemeldete fehlende Seite
(610,9 Sekunden). Das ist weder der vollständige Online-Sale noch der aktuelle
Wochenprospekt. Im neuen Docker-Image bestätigt die echte gemischte
Fünf-Karten-Fixture drei übernommene Sale- und zwei verworfene reguläre Artikel;
ein erneuter vollständiger Liveabruf im Docker wurde nicht zusätzlich behauptet. Die deutsche Parfümerie-Broschüre ist zusätzlich erfasst;
deren Filial-/Onlinegeltung wurde noch nicht ausreichend abgeglichen. Deshalb
keine automatische Übernahme globaler Parfümeriepreise in regionale Angebote.

## dm

Ein genereller Ausfall ließ sich weder über die produktive API noch MCP
reproduzieren: 401 offizielle Ausverkaufsartikel. Der isolierte Test-Docker
bestätigte ebenfalls 401 Artikel ohne Quellenwarnung. Die Rohantwort enthält
405 Produkte; vier ohne Ausverkaufskennzeichnung wurden ausgeschlossen.
**Bei dm wurde kein Wildschwein gesucht oder als Produkt zugeordnet.**

Die API hat aktuell eine Seite. Die bisher ignorierte Seitendeklaration ist
jetzt für mehrere Seiten implementiert und mit simulierten Folgeseiten,
fehlender Seite, Schemafehler und Preisspeicherung getestet. Dies ist ein
Contract-Test, kein behaupteter aktueller Mehrseiten-Livefall. Die fünf
angefragten Produktdetailseiten lieferten eine Challenge; das ist kein Beweis,
dass die separate öffentliche Produkt-API ausgefallen ist. dm veröffentlicht
hier Online-Ausverkauf, keinen erfundenen wöchentlichen Prospektzeitraum.

## Vollständiges Händlerregister und Prüfmatrix

`R/I/S` zählt geprüfte Referenzen in Rohdaten / Import / Suche, soweit unabhängig
zuordenbar. `—` bedeutet offen, nicht null. Die Zahlen gelten nur für die genannte
Stichprobe. „5 beobachtet“ bedeutet keinen abgeschlossenen Fünf-Artikel-Vertrag.

| Händler / Provider-ID | Android / Docker | Primärquelle; Ergänzung/Fallback | geprüfte Region | Referenzen; R/I/S | Fehler / Status / Korrektur |
|---|---|---|---|---|---|
| REWE `rewe` | nativ / ja | offiziell; Marktguru/KaufDA bei Fehler | Köln, Berlin, Leipzig | 5; —/—/— | `SOURCE_UNAVAILABLE`: direkte Referenzabrufe 403; regionaler Prospekt vorhanden, konkrete Marktgeltung offen. Native Metadaten/Preisrundung korrigiert. |
| ALDI Nord `aldi-nord` | nativ / ja | offiziell + kontrollierter KaufDA-Ortsprospekt | Berlin 10115 | 5; 0→5 / 0→5 / 0→5 in regionalem Replay | `UPSTREAM_MISSING`: Viba, Riesa, Eberswalder, Ileburger und Mühlhäuser fehlen im offiziellen Standardfeed, im eigenen Berlin-Prospekt vorhanden. Ergänzung bei gefülltem Katalog getestet. Live-Gesamtabnahme offen. |
| ALDI Süd `aldi-sued` | nativ / ja | offiziell; kein unnötiger Aggregatorersatz | Köln 50939 | 5 Produktseiten; 5/5/5 Preis/Name, vollständige Packungsprüfung offen | `NOT_VERIFIED`: Produktpreise unabhängig bestätigt, keine daraus erfundenen Enddaten. Mehrere Warengruppen/weitere Region offen. |
| Lidl `marktguru-lidl` | nativ / ja | Marktguru + regionaler KaufDA-Viewer | Leipzig, Köln | 5; 5/5/5 Grundstichprobe | `CACHE_STALE`/partielle Quellabrufe und Varianten-Suchlücke behoben; Hirsch-Metadaten `UPSTREAM_MISSING`; weitere Dublettenprüfung offen. |
| PENNY `marktguru-penny` | nativ / ja | Marktguru | Leipzig | 5; 5/5/5 Backwaren | `PARSER_LOSS`: 1.000 g wurde 1 g; expliziter „ohne App“-Preis ergänzt. Donnerstag-Toniebox als Vorschau vorhanden. Weitere Produktgruppen offen. |
| Netto Marken-Discount `netto-marken` | nativ / ja | Marktguru, bestehende Filialwahl | Leipzig | 5; 5/5/5 Name/Preis | `PARSER_LOSS`: ausdrücklich „NETTO APP“ ohne „PLUS“ wurde nicht erkannt; korrigiert. Nicht auf Cashback als Barpreis anwenden. |
| Netto schwarz `netto-schwarz` | nativ / ja | offiziell; vorhandener Marktguru-Fallback | Berlin, Leipzig | 5 Prospektartikel; Filialgeltung —/—/— | Filialsuche aus öffentlichem eingebettetem Store-JSON repariert, 31 Live-Angebote; spezifische Händlerzuordnung vor generischem Netto. Prospektstichprobe noch `NOT_VERIFIED`. |
| Kaufland `kaufland` | nativ / ja | offiziell, filialspezifisch | Köln-Ehrenfeld 4130, Thebäerstraße 9 | 5; 5/5/5 Name/Preis/Pack | Filialadresse unabhängig bestätigt und passend zum regionalen Prospekt. Unabhängige Mitgliedspreis-/Folgewoche-Abnahme offen (`NOT_VERIFIED`). |
| EDEKA `edeka` | nativ / ja | offiziell; vorhandene Fallbacks | Köln Romano, Berlin, Leipzig | 5 Prospektartikel; —/—/— | Heyßel-Prospekt ist kein Romano-Beweis. Neue offizielle Romano-Angebotsseite erreichbar; Abgleich läuft (`NOT_VERIFIED`). |
| Marktkauf `marktkauf` | Servermodus / ja | offizieller EDEKA-Marktadapter | Markkleeberg, zusätzlich Frechen | 5; 5/5/5 Namen/Preise, 4/5 Packungen | `UPSTREAM_MISSING`: Philadelphia-Packungsbereich fehlt bereits im geprüften offiziellen API-Datensatz; auf eigener HTML-Seite vorhanden. Keine erfundene Menge. |
| Globus `globus` | nativ / ja | offizieller Markt-/Faltblattadapter; bestehende Bild-Ergänzung | Köln, Leipzig | 5 beobachtet; —/—/— unabhängig | Native Gültigkeitsdaten und Beschreibung übernommen. Vollständiger unabhängiger Referenzabgleich offen (`NOT_VERIFIED`). |
| famila Nordwest `marktguru-famila-nordwest` | nativ / ja | Marktguru | Oldenburg 26135 | 5; 5/5/5 Name/Preis/Pack | `PARSER_LOSS`: explizite MOIN-CARD-Preise erkannt. Prospekt nennt beim 14.11. falschen Wochentag; keine künstliche Datumsänderung. Weitere Region offen. |
| aktiv & irma `aktiv-irma` | nativ / ja | offizielle Wochen-HTML-Seite | Oldenburg 26135; 26122 negativ | 5 offizielle Karten; 5/5/5 | `DATE_REGION_FILTER`: „gültig ab Donnerstag“ wurde Wochenmontag zugeordnet; produktspezifische Korrektur und Tests ergänzt. |
| Combi `marktguru-combi` | nativ / ja | Marktguru | Oldenburg 26135 | 5; 5/5/5 Namen/Preise | MOIN CARD korrigiert. Prospekt-Varianten 140/150 g bzw. zwei Kistengrößen sind nicht vollständig im Rohdatensatz ausformuliert (`UPSTREAM_MISSING`/Variantenprüfung offen). |
| HOL’AB! `holab` | nativ / ja | offizielle ausgewählte Wochen-HTML-Angebote | Oldenburg 26135 | 5 Karten; 5/5/5, Mengen nach Korrektur | `PARSER_LOSS`: Liter-Schreibweisen und Zwei-Kisten-Preis; 4,49 € ab 2, ausdrücklich 4,99 € einzeln, 8,98 € für 2. Kein Anspruch auf ganzen Prospekt. |
| trinkgut `trinkgut` | nativ / ja | Backend offiziell; Android Marktguru/KaufDA | Köln; andere Testregionen ohne nahen Markt | 5 Produktseiten; Namen/Preise vorhanden, regionale Enddaten — | Öffentliche Produktseite nennt 13.11., ausgewählter Feed 14.11.; Marktgeltung vor Klassifizierung prüfen (`NOT_VERIFIED`). Kein Preis aus anderem Markt übernehmen. |
| Rossmann `rossmann` | nativ / ja | offiziell gerendert; bestehende Fallbacks | Köln | 5 Spielwarenreferenzen; —/—/— | Testhost ohne Chromium nutzte Fallback. Spielwarenprospekt gilt nur bei entsprechendem Sortiment; kein erfundener Verlust außerhalb dieser Filialen (`NOT_VERIFIED`). |
| Müller `mueller` | nativ / ja | offizielle Online-Seiten; bestehende Fallbacks | Online; regionale Parfümerie offen | 5 gemischte Karten: 3 Sale, 2 negative Kontrollen | `PARSER_LOSS`: reguläres Sortiment fälschlich als Angebot interpretiert. Sale-Filter und unabhängige Navigation korrigiert: 2.816 Sale aus neun Kategorien/294 Seiten. Datierten Prospekt weiterhin getrennt abgleichen. |
| dm `dm` | nativ / ja | offizielle Ausverkaufs-API | Online, 04109/50939 geprüft | 5 API-Beobachtungen; Detailseiten-Challenge | 401 Live-Angebote, kein genereller Ausfall. Mehrseiten-/Schema-Vertrag erweitert; unabhängige Detailprüfung `SOURCE_UNAVAILABLE`. |

## Gemeinsame Korrekturen

- Beschreibungen und veröffentlichte Packungsangaben bleiben in Android
  gespeichert und suchbar; Room 7→8 ist additiv. Keine Art-/Tier-Synonyme.
- Exakte Ergänzungen erhalten Primärdaten; unterschiedliche Sorten und Mengen
  werden nicht allein wegen gleichen Preises zusammengeführt. Eine unsichere
  Identität bleibt getrennt und wird nicht als behobene Dublette ausgegeben.
- Temporäre Teilfehler erhalten gültige Offline-Daten desselben Regions-/Markt-
  und Wochenschlüssels, sichtbar als unbestätigt. Undatierte Müller-/dm-Daten
  höchstens 24 Stunden seit ihrer ursprünglichen Bestätigung, nicht seit jedem
  erneuten Fehler. Bestätigte Markt-Abwesenheit darf keine Daten wiederbeleben.
- Neue Backend-Snapshot-Version verhindert, dass alte falsche Packungen,
  Mitgliedspreise oder reguläre Müller-Artikel einfach aus dem alten
  Wochencache als neuer Erfolg ausgegeben werden. Alte DB-Einträge werden
  dadurch nicht destruktiv gelöscht.
- Diagnostik trennt Quell-Erreichbarkeit von Referenzabdeckung. Ein bloß
  abweichender Preis belegt ohne Rohdaten noch keinen Parserfehler.

## Reproduktion und Abnahme

```sh
python -m pip install -e '.[dev]'
python -m pytest
ruff check src tests
bandit -q -r src -ll
pip-audit --local
cd android
./gradlew testStandardDebugUnitTest testFdroidDebugUnitTest \
  assembleStandardDebug assembleFdroidDebug lintStandardDebug lintFdroidDebug
```

`testDebugUnitTest` ist wegen Standard/F-Droid mehrdeutig; beide konkreten
Varianten ausführen. Optionale gespeicherte Live-Rohdaten bleiben lokal, CI
braucht keine Händlerzugänge. Die SQLite-Migration wird mit der echten alten
und neuen Room-Schemadefinition geprüft; JVM-Tests sind kein Gerätetest.

Nach der Müller-Sale- und Donnerstag-Korrektur: Backend 770 bestanden/8
übersprungen; Android 263/266 bestanden, je 1 optionaler Rohdaten-Test
übersprungen; beide Debug-APKs und beide Lint-Varianten erfolgreich. Die zusätzliche Händlerisolation wird auch über MCP geprüft: Lidl-Wildschwein
liefert bei einer ausschließlich auf dm oder Müller eingeschränkten Suche
keinen Treffer. Bandit/Ruff erfolgreich,
Paket-Audit ohne bekannte Schwachstelle nach Update des ausschließlich lokalen
Test-pip. Diese Zwischenzahlen gelten nicht automatisch für spätere Änderungen am Diff.

**Noch offen:** abschließende Referenz-/Dublettenvergleiche, die in der Tabelle
benannten Rohdaten-/Regionsnachweise, finale Sale-Docker-Abnahme, finaler
Diff-Review, Commit/Push/PR/CI und bestätigter Merge. Die produktive Installation
wurde für die Diagnose lesend abgefragt; die Test-Images sind keine bereits
veröffentlichte oder produktiv ausgerollte Version.

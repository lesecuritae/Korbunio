# Händler-Angebotsabdeckung

Stand: 10.11.2026. Ausgangsrevision: `1479643ff66bc54184ff9cdca27b5f1247ce2635`
(0.1.75). **Arbeitsstand, keine vollständige Abnahme und kein Release.**

## Verfahren und Aussagegrenzen

Das Backend registriert 19 Händler. Android besitzt 18 eigenständige native
Provider; Marktkauf ist bisher über den Server erreichbar. Die vollständige
Stichprobenliste steht in [offer-coverage-samples.json](offer-coverage-samples.json):
128 dokumentierte Beobachtungen für alle 19 Händler, darunter ausdrücklich
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

Der diagnostische Abruf aller neun Kategorien benötigte 294 Seiten und 610,9
Sekunden und ergab 2.816 ausdrücklich markierte Sale-Produkte. Das ist kein
Wochenprospekt. Der normale Müller-Provider verwendet jetzt stattdessen den
datierten eigenen Händlerprospekt (Viewer 2501311481): 89 Artikel, gültig
02.–14.11.2026. Der reale Abruf über den Hauptloader und vier Testregionen
bestätigt diesen Import. Die sieben ausgewählten veröffentlichten Artikel werden
mit Preis, Menge und Datum in Backend und Android geprüft. Beispielsweise bleibt
ISSEY MIYAKE 42,95 € regulär und 37,95 € mit der ausdrücklich benannten App.

Der Prospekt besitzt keine verifizierte Filialbindung. Deshalb heißt die Quelle
`KaufDA-Händlerprospekt` und der Hinweis „Filialgeltung und lokaler Bestand nicht
bestätigt“ bleibt sichtbar. Es gibt keine erfundene regionale Verfügbarkeit und
keinen stillen Rückfall auf den riesigen Sale-Katalog. Der eigenständige alte
Sale-Parser bleibt mit seinen negativen Kontrollen getestet.

## dm

Ein genereller Ausfall ließ sich weder über die produktive API noch MCP
reproduzieren: 401 offizielle Ausverkaufsartikel. Der isolierte Test-Docker
bestätigte ebenfalls 401 Artikel ohne Quellenwarnung. Die Rohantwort enthält
405 Produkte; vier ohne Ausverkaufskennzeichnung wurden ausgeschlossen.
**Bei dm wurde kein Wildschwein gesucht oder als Produkt zugeordnet.**

Die aktuelle öffentliche Produkt-API ist erreichbar. Ihr Gesamtbestand änderte
sich während der Beobachtungen von 405 auf 441 Rohprodukte; die vollständig
gespeicherte, geprüfte Ausverkaufsstichprobe enthält 401 Angebote. Das sind
unterschiedliche Beobachtungszeitpunkte, keine zugesicherte konstante Anzahl.
Gesamtzahl, Seitenindex und deklarierte letzte Seite werden jetzt geprüft.
Eine leere letzte Seite oder eine erfolgreiche, aber verkürzte JSON-Antwort
ist ein Fehler und darf gültige Offline-Daten nicht als vollständiger Import
ersetzen. Backend und Android besitzen entsprechende Regressionstests.

In Android kamen zwei weitere Ursachen hinzu: `1 St` wurde nicht als Menge
erkannt; im Servermodus wurde JSON-`null` in die Zeichenfolge „null“ verwandelt.
Damit wurden undatierte dm-Angebote unsichtbar. Mengen und echte fehlende
Datumswerte bleiben jetzt erhalten. Die fünf Detailseiten-Challenges beweisen
keinen Ausfall der separaten öffentlichen Produkt-API. Der Online-Ausverkauf
erhält keinen erfundenen wöchentlichen Prospektzeitraum.

## ALDI Süd: temporärer DNS-Gegentest

Die fehlgeschlagenen Prospektabrufe waren auf diesem Testhost durch NextDNS
verursacht: Händlerdomain und `blockpage.nextdns.io` wurden auf dieselben
Sperrseiten-Adressen aufgelöst, mit einem NextDNS-Sperrseiten-Zertifikat.
Mit ausdrücklicher Freigabe wurde am 10.11. nur im Diagnoseprozess die öffentliche
DNS-Auflösung verwendet. Keine System-DNS-, Container- oder TLS-Einstellung
wurde verändert. HTTPS antwortete mit 200 und gültiger Zertifikatsprüfung.

Der eigene Wochenprospekt `kw46-26-op-mp` lieferte 151 importierbare Angebote aus
17 abgefragten Dokumenten. Ein anschließender lokaler Replay nutzt genau diese
gespeicherten Antworten; seine Laufzeit ist keine Netzwerkgeschwindigkeit.
Die fünf ersten Rohprodukte werden zusätzlich als kleiner öffentlicher
Fixture-Vertrag geprüft: Gurke 0,75 €, Mango 1,19 €, Äpfel 2 kg 1,99 €,
Puten-Ministeaks 400 g 4,59 €, Hamburger 400 g 4,39 €, jeweils 09.–14.11.
Fehlende Gewichte von Gurke/Mango bleiben leer. Die 151 beweisen keine
vollständige Prospektabdeckung. Der normale DNS-Filter bleibt unverändert;
eine dauerhafte Freigabe oder Benutzerkonfiguration ist nicht ausgerollt.

## Vollständiges Händlerregister und Prüfmatrix

`R/I/S` zählt geprüfte Referenzen in Rohdaten / Import / Suche, soweit unabhängig
zuordenbar. `—` bedeutet offen, nicht null. Die Zahlen gelten nur für die genannte
Stichprobe. „5 beobachtet“ bedeutet keinen abgeschlossenen Fünf-Artikel-Vertrag.

| Händler / Provider-ID | Android / Docker | Primärquelle; Ergänzung/Fallback | geprüfte Region | Referenzen; R/I/S | Fehler / Status / Korrektur |
|---|---|---|---|---|---|
| REWE `rewe` | nativ / ja | offiziell; Marktguru/KaufDA bei Fehler | Köln, Berlin, Leipzig | 5 alte regionale + 5 neue marktgebundene Referenzen; neuer direkter Markt-Abruf 188 Karten / 184 Angebote / 4 reine Bonuskarten | Frühere 403-Detailseiten nicht auf den erreichbaren Marktadapter übertragen. Drei alte allgemeine Referenzen sind im ausgewählten Markt nicht belegt (`NOT_VERIFIED`); kein nachgewiesener Parserverlust. Native Metadaten/Preisrundung korrigiert. |
| ALDI Nord `aldi-nord` | nativ / ja | offiziell + kontrollierter KaufDA-Ortsprospekt | Berlin 10115 | 5; 0→5 / 0→5 / 0→5 in regionalem Replay | `UPSTREAM_MISSING`: Viba, Riesa, Eberswalder, Ileburger und Mühlhäuser fehlen im offiziellen Standardfeed, im eigenen Berlin-Prospekt vorhanden. Ergänzung bei gefülltem Katalog getestet. Live-Gesamtabnahme offen. |
| ALDI Süd `aldi-sued` | nativ / ja | offizielle Webangebote/strukturierter Wochenprospekt | Köln; separater temporärer DNS-Gegentest | 5 Produktseiten + 5 echte Prospektdatensätze; 151 Prospektimporte | `SOURCE_UNAVAILABLE` im normalen NextDNS-Testnetz; mit temporärer öffentlicher Auflösung HTTPS und Parser erfolgreich. Kein TLS-Bypass oder produktiver DNS-Wechsel. |
| Lidl `marktguru-lidl` | nativ / ja | Marktguru + regionaler KaufDA-Viewer | Leipzig, Köln | 5; 5/5/5 Grundstichprobe | `CACHE_STALE`/partielle Quellabrufe und Varianten-Suchlücke behoben; Hirsch-Metadaten `UPSTREAM_MISSING`; weitere Dublettenprüfung offen. |
| PENNY `marktguru-penny` | nativ / ja | Marktguru | Leipzig | 5 Backwaren + 5 weitere Warengruppen; Name/Preis in Quelle vorhanden | `PARSER_LOSS`: 1.000 g wurde 1 g; expliziter „ohne App“-Preis ergänzt. Donnerstag-Toniebox als Vorschau vorhanden. Zusätzlicher Coverabgleich: Kaffee, Joghurt, Pasta, Saft und Toniebox. Je-Stück-Angabe der Toniebox fehlt im strukturierten Ausgangsdatensatz (`UPSTREAM_MISSING`). |
| Netto Marken-Discount `netto-marken` | nativ / ja | Marktguru, bestehende Filialwahl | Leipzig | 5; 5/5/5 Name/Preis | `PARSER_LOSS`: ausdrücklich „NETTO APP“ ohne „PLUS“ wurde nicht erkannt; korrigiert. Nicht auf Cashback als Barpreis anwenden. |
| Netto schwarz `netto-schwarz` | nativ / ja | offiziell; vorhandener Marktguru-Fallback | Berlin, Leipzig | 5 Prospektartikel; 338 reale Filialdatensätze geprüft | `DATE_REGION_FILTER`/`PARSER_LOSS`: autoritatives initialStores, bestätigte deutsche PLZ-Koordinaten und 15-km-Grenze; Android prüft vor sämtlichen Fallbacks. Berlin positiv/Oldenburg negativ. Ganze Europreise erhalten; vier App-only-Karten ohne eindeutigen Normalpreis nicht als regulär erfinden. Zwei alte Prospektreferenzen fehlen schon in der offiziellen Angebotsseite (`UPSTREAM_MISSING`). |
| Kaufland `kaufland` | nativ / ja | offiziell, filialspezifisch | Köln-Ehrenfeld 4130, Thebäerstraße 9 | 5; 5/5/5 Name/Preis/Pack | Filialadresse unabhängig bestätigt und passend zum regionalen Prospekt. Unabhängige Mitgliedspreis-/Folgewoche-Abnahme offen (`NOT_VERIFIED`). |
| EDEKA `edeka` | nativ / ja | offizieller ausgewählter Markt, moderne HTML-Angebote vor Legacy-API | Köln Romano 070696/12145; Berlin/Leipzig Legacy | 9 reale Dialoge im Vertrag, 224 live | `PARSER_LOSS`: Legacy verlor App-Preise. Reguläre/App-Preise, Pfand, GTIN und Packung aus marktgebundener HTML-Seite; 220/220 bestehende IDs eindeutig weiterverwendbar. Kein fremder Markt als Ersatz. |
| Marktkauf `marktkauf` | Servermodus / ja | offizieller Marktadapter + eigene Markt-HTML für fehlende Mengen | Markkleeberg; Frechen | 5; 5/5/5 Name/Preis, nun 5/5 Mengen | `PARSER_LOSS`/Quellenlücke: Philadelphia 100–195 g aus derselben offiziellen Wochenkarte ergänzt. Nur fehlende, eindeutig zuordenbare Mengen; keine Preis-/Datumsüberschreibung. |
| Globus `globus` | nativ / ja | offizieller Markt-/Faltblattadapter; bestehende Bild-Ergänzung | Köln, Leipzig | 5 unabhängig auf dem marktgebundenen Cover geprüft; 5/5 Import im gespeicherten Replay | `PARSER_LOSS`: mein-GLOBUS-Preispaare und Packungs-/Grundpreisspannen korrigiert. Explizite Durchmesser-/Preispaare einzeln, andere ab-Gruppen ohne erfundenen Festpreis. Neuer Docker-Live-Lauf offen. |
| famila Nordwest `marktguru-famila-nordwest` | nativ / ja | Marktguru | Oldenburg 26135 | 5; 5/5/5 Name/Preis/Pack | `PARSER_LOSS`: explizite MOIN-CARD-Preise erkannt. Prospekt nennt beim 14.11. falschen Wochentag; keine künstliche Datumsänderung. Weitere Region offen. |
| aktiv & irma `aktiv-irma` | nativ / ja | offizielle Wochen-HTML-Seite | Oldenburg 26135; 26122 negativ | 5 offizielle Karten; 5/5/5 | `DATE_REGION_FILTER`: „gültig ab Donnerstag“ wurde Wochenmontag zugeordnet; produktspezifische Korrektur und Tests ergänzt. |
| Combi `marktguru-combi` | nativ / ja | Marktguru | Oldenburg 26135 | 5; 5/5/5 Namen/Preise | MOIN CARD korrigiert. Prospekt-Varianten 140/150 g bzw. zwei Kistengrößen sind nicht vollständig im Rohdatensatz ausformuliert (`UPSTREAM_MISSING`/Variantenprüfung offen). |
| HOL’AB! `holab` | nativ / ja | offizielle ausgewählte Wochen-HTML-Angebote | Oldenburg 26135 | 5 Karten; 5/5/5, Mengen nach Korrektur | `PARSER_LOSS`: Liter-Schreibweisen und Zwei-Kisten-Preis; 4,49 € ab 2, ausdrücklich 4,99 € einzeln, 8,98 € für 2. Hemelinger-Kisten bleiben Alternativen statt Summenpack; Pfand/Grundpreis ohne Variantenwahl nicht eindeutig. Kein Anspruch auf ganzen Prospekt. |
| trinkgut `trinkgut` | nativ / ja | Backend offiziell; Android Marktguru/KaufDA | Köln; andere Testregionen ohne nahen Markt | 5 Produktseiten + 1 Bonuskarte; Namen/Preise vorhanden, regionale Enddaten —; live 73 Karten, 0 unlesbar | `PARSER_LOSS` behoben (`00f4b6e`): Karte mit PAYBACK-Punkteplakette vor dem Preis ging verloren; abgeschnittener Grundpreisbezug „(1 l =...“ galt als zweite Packung. Punkte bleiben Bedingung, kein Preisnachlass. Öffentliche Produktseite nennt 13.11., ausgewählter Feed 14.11.; Marktgeltung `NOT_VERIFIED`. Kein Preis aus anderem Markt übernehmen. |
| Rossmann `rossmann` | nativ / ja | offiziell gerendert; vorhandene Fallbacks | Docker-Chromium; regionale Filialgeltung offen | 24 reale offiziell gerenderte Angebote; 5 aktuelle Werbekarten mit Preis/Pack/Datum | `PARSER_LOSS`/`DATE_REGION_FILTER`: primäre Packung statt addierter Erläuterungen, nur datierte Werbeangebote, aktuelle/Folgewoche getrennt. Fünf zusätzliche tatsächliche Online-Referenzen; örtlicher Filialbestand bleibt `NOT_VERIFIED`. |
| Müller `mueller` | nativ / ja | datierter eigener KaufDA-Händlerprospekt; kein allgemeiner Sale-Ersatz | reale PLZ-Koordinaten; Filialgeltung ausdrücklich offen | 7 veröffentlichte Artikel im Vertrag; 89 live | `PARSER_LOSS` behoben: Sortiment nicht länger als Wochenangebote. Eigener Herausgeber, Datierung und App-Preis geprüft; örtlicher Bestand `NOT_VERIFIED`. |
| dm `dm` | nativ / ja | offizielle Ausverkaufs-API | Online; Leipzig/Köln | 5 offiziell abgeglichene API-Preis-/Mengen-/Ausverkaufskennzeichnungen; Detailseiten-Challenge | `PARSER_LOSS`: native Mengen und Server-Nullwerte korrigiert. 401 beobachtete Ausverkaufsangebote; deklarierte Gesamtzahl und fehlende letzte Seite geprüft. Detailseiten weiterhin `SOURCE_UNAVAILABLE`. |

## Gemeinsame Korrekturen

- Beschreibungen und veröffentlichte Packungsangaben bleiben in Android
  gespeichert und suchbar; Room 7→8 erhält vorhandene Daten. Der eindeutige Namensindex wird zu einem nicht eindeutigen Suchindex, damit zwei gleichnamige Produkte mit verschiedenen GTINs erhalten bleiben. Provider werden zur erneuten Prüfung markiert; gespeicherte Favoriten und Angebote bleiben bestehen. Nur einseitige allgemeine Wildgulasch-Suche auf ausdrücklich benannte Gulascharten, keine erfundene Hirschvariante.
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

Letzte vollständige Python-Prüfung: **801 bestanden, 8 übersprungen**, einschließlich des Vertrags für fünf tatsächlich gelesene ALDI-Süd-Prospektprodukte.
Android Standard: **280 bestanden, 1 übersprungen**; F-Droid: **283 bestanden, 1 übersprungen**; jeweils keine Fehler. Beide Debug-APKs und beide Lint-Varianten sind erfolgreich gebaut. Die Zahlen stammen aus den JUnit-XML-Dateien.
Die Korrekturen sind lokal in `0d2b19358ce982cb2d5bc2a7bf80656a888b13a5` gesichert; der eigenständige Docker-Abnahmelauf wird daran gebunden. Ruff und Diff-Prüfung sind erfolgreich.

Im Serveradapter sind außerdem gleiche Titel mit verschiedenen GTINs getrennt,
Quellenwarnungen und Teilimportstatus erhalten, Wochenwahl weitergereicht und
Pagination begrenzt. Seitenlinks auf einen anderen Ursprung werden vor einer
Tokenweitergabe abgelehnt. Die Migration wird anhand der tatsächlichen alten und
neuen Room-Schemata mit SQLite geprüft; das ersetzt keine Installation auf einem
Android-Gerät.

### Isolierter Docker-Live-Test des gesicherten Codes

Code `0d2b19358ce982cb2d5bc2a7bf80656a888b13a5`, Image
`sha256:7721ed762e1ab903eaad819d40128517e18f200e27400dc46af8c1228aba6833`.
Eigenständiger, auf Loopback begrenzter Testcontainer mit temporärem öffentlichem
DNS; danach gestoppt und entfernt. Keine produktive Installation ersetzt.

| Quelle | tatsächlich importiert | Ergebnis |
|---|---:|---|
| dm | 401 | offizielle Ausverkaufs-API, keine Warnung |
| Müller | 89 | datierter Händlerprospekt; Filialgeltung ausdrücklich ungeklärt |
| Lidl | 803 | Marktguru plus verifizierter Ortsprospekt; keine Bestandszusage |
| EDEKA Romano | 224 | ausgewählter offizieller Markt, keine Quellenwarnung |
| HOL’AB! | 6 | ausgewählte Wochenkarten, keine Quellenwarnung |
| ALDI Süd | 151 | offizieller Wochenprospekt, temporärer DNS-Test ohne Warnung |

Alle sechs realen API-Importe und zehn MCP-Suchen bestanden die anschließend
geprüften Erwartungen: Lidl-Wildschwein/Wildgulasch vorhanden, Hirschgulasch
nicht erfunden; dm-Seifendose und Müller-Alien vorhanden; keinerlei
Lidl-Wildschwein in einer nur auf dm oder Müller beschränkten Suche. EDEKA
Ritter Sport zeigt 1,11 € regulär und 0,88 € mit App. Vilsa bleibt 4,49 € je
Kiste ab zwei, 8,98 € für zwei, 4,99 € einzeln. ALDI-Puten-Ministeaks bleiben
4,59 €, 400 g, 09.–14.11.2026. Müller/Lidl liefern wegen ihrer erklärten
Geltungsgrenzen konservativ `partial`, ohne daraus einen technischen Abruffehler
zu erfinden. Diese Beobachtungszahlen beweisen keine landesweite Vollständigkeit.

### Ergänzung: ausdrücklich veröffentlichter Sechserkarton

Die gleiche reale HOL’AB!-Fixture nennt für Rauch Happy Day 1,99 € je Packung
und ausdrücklich 10,00 € für den Sechserkarton. Backend und Android übernehmen
diesen Mengenpreis als gesonderte Mehrkaufaktion. Für eine, sechs und sieben
Packungen ergeben die Regressionstests 1,99 €, 10,00 € und 11,99 €.
Es wird kein Preis aus dem Grundpreis errechnet. App-/Couponbedingungen,
mehrdeutige Kartonpreise und ungültige Mengen sperren die automatische
Zuordnung. Der veröffentlichte Detailtext bleibt erhalten.

Der vollständige Backendlauf nach dieser Ergänzung besteht **804 Tests**, bei
8 übersprungenen Live-/optionalen Tests. Android: **281 Standard- und 284
F-Droid-Tests bestanden**, jeweils ein optionaler Test übersprungen; beide APKs
und beide Lint-Läufe erfolgreich. Code `66095e21f51e17b0c170e5febab31ae82ad55a98`, Image
`sha256:01af25f0e65fd2c7478b3a55d449b0e503195f07d7082193470e99e4d1679621`: Der zusätzliche tatsächliche API- und MCP-Abruf bestätigt
6 Packungen für 10,00 € bei ausdrücklich erhaltenem Einzelpreis 1,99 €.
Der separate Testcontainer samt temporärem DNS wurde anschließend entfernt.
Dieser Nachweis ergänzt die oben an `0d2b193` gebundenen sechs Importe und
zehn MCP-Suchen; er ersetzt sie nicht rückwirkend durch einen anderen Stand.

**Noch offen:** abschließende Referenz-/Dublettenvergleiche, die in der Tabelle
benannten Rohdaten-/Regionsnachweise, weitere unabhängige Händler-/Regionsnachweise und anschließender Git-Abschluss
mit Push/PR/CI und bestätigtem Merge. Der hier getestete Code ist lokal committet;
ein Push, Merge oder produktives Release hat noch nicht stattgefunden. Die produktive Installation
wurde für die Diagnose lesend abgefragt; die Test-Images sind keine bereits
veröffentlichte oder produktiv ausgerollte Version.


### Nachprüfung: Identität, Pagination und regionale Autorität

Die Room-Migration allein verhinderte keine Namens-Kollisionen beim Import.
Alle drei nativen Importpfade nutzen jetzt dieselbe Identitätsprüfung: GTIN
oder quellgebundene Produkt-ID, niemals nur den Namen. Bereits vorhandene
Favoriten behalten ihre eindeutige Zuordnung; widersprüchliche GTINs werden
nicht überschrieben. Der Serveradapter erzeugt stabile Produktidentitäten aus
den Produktmerkmalen, unabhängig von Wochenpreis und Reihenfolge. Ein
Teilimport erhält die betroffenen tatsächlichen Händler-IDs, statt allein die
technische Server-Provider-ID zu markieren.

Marktguru-Pagination prüft jetzt auch die deklarierte Gesamtzahl: Eine kurze
Seite vor dem angekündigten Ende ist kein vollständiger Abruf. Fehlende Seiten,
widersprüchliche Zähler und spätere HTTP-Fehler erhalten nachweislich schon
empfangene Daten mit sichtbarem Teilstatus. Ein einzelner erfolgreicher Aufruf
belegt weiterhin keine vollständige Prospektabdeckung.

Netto schwarz verwendet in Android und Backend nur den öffentlichen
`initialStores`-Filialkatalog. Exakte Filial-PLZ ist unmittelbar belegbar;
ansonsten müssen Land, PLZ und Koordinaten der Geocodierung bestätigt sein.
Bestätigte Markt-Abwesenheit löst keinen überregionalen Aggregator-Fallback
aus. Der reale neue Backend-Abruf bestätigte Berlin 10115 positiv und Oldenburg
26135 negativ. Die optionale native Wiederholung des gespeicherten vollständigen
338-Filialkatalogs bestand ebenfalls. Fehlerhafte Geocodierung bleibt ein Fehler
und wird nicht als fehlende Filiale ausgegeben.

### Nachprüfung: Globus-Preisvarianten

Das offizielle Köln-Marsdorfer Cover bestätigt die fünf Lebensmittelreferenzen
und die Gültigkeit 09.–14.11. Geramont kostet 2,29 € regulär / 1,99 € mit mein
GLOBUS; Dr. Oetker 1,79 € / 1,69 €. Der Adapter hatte `mgprice` bislang verloren.
Die Mengen 100–200 g und 270–410 g bleiben Spannen: Ihr unterer Grundpreis ist
kein allgemeingültiger einzelner Grundpreis.

Explizit gebundene Pfannendurchmesser 20/24/28 cm werden mit den veröffentlichten
9,99/11,99/13,99 € getrennt übernommen. Uneindeutige Preisbereiche, fehlende
Zuordnungen oder widersprüchliche Paare werden nicht aus dem Gruppenminimum
berechnet. Backend führt solche Gruppen als ungepreist/nicht vergleichbar mit
Hinweis; Android verweigert ihren Festpreisimport mit Quellenwarnung. Der
vollständige gespeicherte offizielle Antwort-Replay ergab vor der letzten
Verschärfung 37 solche Gruppen; dies ist kein neuer Live-Abruf und kein Beleg
vollständiger Variantenabdeckung. Neue Regressionen verhindern auch eine
stillschweigend abgeschnittene, nur teilweise eindeutige Variantenliste.

Aktueller Backend-Nachlauf: **834 bestanden, 8 übersprungen**. Die älteren
Abnahmezahlen und Image-SHAs oben dokumentieren ihre jeweils bezeichneten
Zwischenrevisionen; sie gelten nicht automatisch für den neuesten Code.
Android-Nachlauf: Standard **302 bestanden, 2 übersprungen**, F-Droid
**305 bestanden, 2 übersprungen**, jeweils keine Fehler. Beide APKs und beide
Lint-Prüfungen erfolgreich. Die zwei optionalen Live-Rohdaten-Replays waren
in diesem Lauf nicht aktiviert; der vollständige Netto-Katalog-Replay wurde
separat erfolgreich ausgeführt. Code-Revision: `0cab3e6`. Die Docker-Endabnahme
dieser Revision ist noch offen. Keine produktive Installation wurde
durch diese lokalen Änderungen ersetzt.


### Native REWE-Nachladung und verbleibende Prüfgrenzen

Die offizielle Seite des gewählten REWE-Markts 1940016 besitzt 188 eindeutige
NAN-Referenzen, aber nur einen kleinen fertig gerenderten Ausschnitt. Android
lädt fehlende Karten jetzt über REWEs bestehenden öffentlichen
`/api/frontend-includes` nach, in begrenzten 25er-Batches mit exakter
Markt-/Anfrage-ID-Prüfung. Fehlende, fremde und doppelte Antworten sind Fehler.
Vollständig gelesene offizielle Marktdaten werden nicht mehr wegen einer
höheren Aggregator-Anzahl ersetzt. Ein nötiger regionaler Ersatz trägt die
Warnung fehlender bestätigter Filialgeltung.

Ein vollständiger gespeicherter Katalogtest deckte eine zusätzliche Themenkarte
mit derselben NAN auf einem untergeordneten Link auf. Diese war keine neue
Produktvariante. Platzhalter werden von solchen Links getrennt und anhand der
veröffentlichten NAN dedupliziert. Erwartung: 184 normale Angebote und vier
reine Bonuskarten ohne erfundenen Barpreis. Produktidentitäten folgen der
Markt-/NAN-Kombination statt Titel oder Kartenreihenfolge. Eine nachträgliche
Zuordnung alter ausschließlich namensbasierter Favoriten wird ohne eindeutige
Quellidentität nicht erfunden; vorhandene Datensätze bleiben erhalten.

Backend: Unbekannte Karten bei ansonsten gefülltem REWE-Katalog liefern jetzt
sichtbar `PartialOffers`, statt einen stillschweigend vollständigen Import zu
behaupten. Fünf neue tatsächliche Marktreferenzen ergänzen die drei alten,
nicht für diesen Markt belegten Prospektbeobachtungen. Die genaue tägliche
Gültigkeit ist auf den einzelnen Karten nicht unabhängig aufgedruckt; die
Anwendung verwendet ihre geprüfte Kalenderwochen-Regel, die Referenzdatei
kennzeichnet diese Grenze ausdrücklich.

Der neueste Backendlauf besteht **836 Tests, 8 übersprungen**. Kleine Fixtures
und vollständige gespeicherte Antworten sind Offline-Nachweise, keine echte
Android-Geräteabnahme. Der gesamte Händler-Liveabruf im unveränderten Image
`sha256:464285209f50e659e42e57116e0c66de921b0ed7a4da8a64e41c53ea3120bb27`
(Code `0cab3e6`) lief in 26135, 10115, 50939 und 04109 erfolgreich bis zum
Ergebnis durch. Reale Marktguru-Timeouts in Berlin, nicht vorhandene passende
Marktkauf-/REWE-Märkte in Oldenburg und unbestätigte EDEKA-Marktanzeige blieben
sichtbar; erfolgreicher Controllerabschluss bedeutet keinen Erfolg jeder Quelle.
Drei reale API- und zwei MCP-Prüfungen dieses Images bestätigten Globus-
Normal-/Kundenpreis, die drei individuellen Pfannenpreise und bestätigte
Netto-schwarz-Abwesenheit in Oldenburg. Testcontainer und temporärer DNS wurden
entfernt. Der nachfolgende REWE-Patch benötigt seine eigene endgültige Image-
Abnahme; die alte Image-SHA wird nicht als Beleg für neueren Code verwendet.


### Letzter geprüfter Codestand

`6097286` enthält den nachgeprüften REWE-Fix. Vollständige native Abnahme mit
aktiviertem 188-Karten-Replay: **Standard 306 bestanden, F-Droid 309 bestanden,
jeweils 2 optionale andere Rohdaten-Replays übersprungen, keine Fehler**.
Beide Debug-APKs und beide Lint-Varianten sind erfolgreich. Der erste volle
Replay hatte die oben beschriebene Dublette aufgedeckt; erst der korrigierte
Nachlauf wurde als bestanden gewertet.

`6e647f5` verhindert zusätzlich einen falschen Literpreis bei einer von trinkgut
serverseitig abgeschnittenen zweiten Kistenmenge (`20 x 0,5 l / 24 x 0,3...`).
Die bekannte erste Menge wird dann nicht stellvertretend für die unbekannte
Alternative verwendet. Vollständig lesbare Alternativen und vollständig lesbare
Packungen mit später abgeschnittenem Pfandtext bleiben erhalten. Quellenhinweis
und fehlende Menge bleiben sichtbar. Die abweichende Datierung 13./14.11.
zwischen ungewählter Detailseite und Markt-Liste wird nicht künstlich gleichgesetzt.

Nach diesem letzten Backend-Fix: **840 bestanden, 8 übersprungen**, Ruff,
Bandit und `git diff --check` erfolgreich. `pip-audit --local` meldet keine
bekannte Schwachstelle in den geprüften Abhängigkeiten; das eigene lokale
Projektpaket besitzt keinen passenden PyPI-Auditdatensatz und wird ausdrücklich
als nicht prüfbar angezeigt. Die fünf dm-API-Beobachtungen wurden gegen die
tatsächlichen Rohfelder für Titel, Einzelmenge, Preis und Ausverkaufskennzeichnung
abgeglichen. Das hebt die Detailseiten-Challenge und fehlende Filialbestands-
prüfung nicht auf.

### Unveränderter letzter Docker-Stand

Code `6e647f55d471b4a169d3f01d544d4abfd15683a3`, Image
`sha256:a07b3d3573368c75f16512d99113472e0dcaa6be4490057f854e61b7c09b1f82`.
Kein Quellcode-Overlay, alle 19 registrierten Händler im jeweiligen regionalen
Loader-Lauf berücksichtigt. Die Zahlen unten sind Loader-Importmengen vor der
API-Auswahl, keine behauptete Prospektvollständigkeit.

| PLZ | importierte Datensätze | Dauer | sichtbare Einschränkungen |
|---|---:|---:|---|
| 26135 | 3689 | 20,4 s | kein passender offizieller REWE-/Marktkauf-Markt; REWE-Ersatzquelle gekennzeichnet |
| 10115 | 3123 | 60,4 s | unter anderem Marktguru-Timeouts und nicht unabhängig abgeglichene EDEKA-Marktanzeige |
| 50939 | 3589 | 89,4 s | Marktguru-Teilabrufe; 37 ungeklärte Globus-ab-Gruppen; zwei abgeschnittene trinkgut-Packungsalternativen |
| 04109 | 3761 | 29,7 s | EDEKA-/HOL’AB!-Grenzen und 43 ungeklärte Globus-ab-Gruppen |

Die optionalen KaufDA-Globus-Bildabrufe lieferten teilweise HTTP 404. Der
Bildfehler verwirft keine offiziellen Angebote und wird nicht mit einem
beliebigen anderen Produktbild verdeckt. Das ist kein Nachweis erfolgreicher
Bildversorgung sämtlicher Artikel.


### Im Endlauf zusätzlich reproduziert: KaufDA hebt bereits die Folgewoche hervor

Der Endlauf von `6e647f5` bestand den vollständigen Loader-Abruf, aber **nicht**
die anschließende Wildschwein-Suchabnahme: Kania Wildgerichte war vorhanden,
Wildschwein fehlte. Der fehlgeschlagene Test wurde nicht als Erfolg gewertet.
Die live erfasste Leipziger Seite zeigte unter `brochures.viewer` bereits
Prospekt 2501324813 mit Gültigkeit 16.–21.11.; der weiterhin verlinkte aktuelle
Prospekt 2501324792 (09.–14.11.) stand unter `brochures.publisher`. Die bisherige
Auswahl las nur `viewer`. Auch das frühere Publikationsdatum der Vorschau darf
nicht als aktuelle Angebotsgültigkeit verstanden werden.

Die Korrektur liest beide eigenen Herausgeberlisten, prüft Herausgeber und
Gültigkeit für die angefragte Woche und bevorzugt passende Wochenprospekte vor
parallel verlinkten langfristigen Preis-/Geschenkekatalogen. Fehlende Wochen-
prospekte und überschrittene Grenzen werden als Fehler gemeldet, statt die
Liste still auf zwei Prospekte zu kürzen. Kein anderes Händler-/Themenkarussell
wird zur vermeintlichen regionalen Herkunft erklärt.

Der reale erneute Abruf mit tatsächlich ermittelten PLZ-Koordinaten lieferte
**393** passende KaufDA-Angebote einschließlich Kania Wildschwein 3,99 €,
400 g, 09.–14.11. und der veröffentlichten spezifischen Quellkategorie
Wildschweingulasch. Die neue minimale Metadaten-Fixture reproduziert den
Karussellwechsel. Eine echte Dessert-Referenz aus dem Folgeprospekt prüft
zusätzlich 2,49 € normal / 1,99 € mit Lidl Plus, 125 g, 16.–21.11.; sie darf
nicht rückwirkend in die laufende Woche aufgenommen werden.

Diese Korrektur erfordert einen neuen getesteten Docker-Stand. Die oben
festgehaltenen Importzahlen des vorherigen Images bleiben als Zwischenstand
erhalten und werden nicht in neue Erfolgsnachweise umbenannt.


### Bestätigter Nachlauf nach dem Karussell-Fix

Coderevision `ddd47d6f2a91f3f9a60e383f700bae17cd72c460`, unverändertes Image
`sha256:864dd70df50d277bc16fa6dde86e826a7c1533ce81ae9b5a7941a4f8c2af5382`.
**842 Backendtests bestanden, 8 übersprungen; Android Standard 307 bestanden,
F-Droid 310 bestanden, jeweils 2 übersprungen**, mit aktiviertem vollständigen
REWE-Replay. Beide APKs und Lint-Varianten, Ruff, Bandit und Diff-Prüfung bestanden.

**14 reale API-Prüfungen und 7 reale MCP-Prüfungen dieses Images bestanden.**
Kania-Wildschwein ist nach der Wochenprospekt-Korrektur wieder über Docker/API
und MCP suchbar. Nur auf dm oder Müller begrenzte Wildschwein-Suchen bleiben
leer. Hirschgulasch wird weiterhin nicht aus einem generischen Kania-Datensatz
erfunden. Weitere tatsächlich geprüfte Fälle: Globus-Normal-/Kundenpreis und
drei individuelle Pfannenpreise, EDEKA 1,11/0,88 €, Rauch-Mehrkauf 6 für 10 €,
REWE-Joghurt 1,19 € plus 0,15 € Pfand, trinkgut ohne falschen Literpreis,
Netto-Trefl 8 € und bestätigte Markt-Abwesenheit in Oldenburg. Netto schwarz
wurde außerdem in Berlin 10115 und 13353 positiv geprüft; ALDI Süd in 50939
und 80331. Produktpreise sind Test-Erwartungen aus den datierten veröffentlichten
Referenzen, keine Laufzeitkonstanten.

Testcontainer und temporäre DNS-Einstellung wurden danach entfernt. Die
produktive Installation wurde nicht ersetzt; ein signiertes neues APK-Release
wird durch diese lokalen Debug-Builds nicht behauptet. Der abschließende
Vier-Regionen-Loader-Nachlauf dieser Revision wird separat protokolliert.


### Abschließender Stand: trinkgut-Bonuskarte und endgültiger Nachlauf

Der Loader-Lauf von `ddd47d6` meldete für den Kölner trinkgut-Markt 72 Angebote
und eine nicht auswertbare Karte. Die gespeicherte Karte zeigte sichtbar
„250 Extra °P“, 8.99 und Grasovka Vodka 0,5 l. Ursache war kein fehlender
Quelldatensatz: Die PAYBACK-Punkteplakette trägt dieselbe Klasse wie der Preis
und steht davor; der Parser las den ersten Treffer, fand darin keinen Preis und
verwarf die Karte (`PARSER_LOSS`). `00f4b6e` überspringt Bonusplaketten beim
Preislesen und führt die veröffentlichten Punkte als Angebotsbedingung
„Punkte, kein Preisnachlass“. Es wird kein Euro-Gegenwert berechnet. Eine Karte,
die nur eine Punkteplakette und keinen Preis enthält, bleibt unlesbar und
sichtbar teilweise.

Der Regressionstest deckte einen zweiten, allgemeinen Fehler auf: Ein vor der
schließenden Klammer abgeschnittener Grundpreisbezug („0,5 l Flasche (1 l =...“)
wurde als zweite Packung 1000 ml gewertet. Die Packungserkennung entfernt nun
auch die abgeschnittene Form; ein nicht als Grundpreis erkennbarer Klammertext
bleibt unverändert.

Coderevision `00f4b6edabf0ea10ea7ca5c9466e19e9c3c9c406`, Image
`sha256:6ed3d3f4fb8efe7c4511fc667fcd9830559db5585ab580ba267980e8439a7aa9`.
**849 Backendtests bestanden, 8 übersprungen**; Ruff, Bandit und Diff-Prüfung
bestanden. Der Android-Code ist gegenüber `ddd47d6` unverändert (trinkgut läuft
nativ über Marktguru/KaufDA, nicht über diesen Parser); die dortigen
Ergebnisse 307/310 wurden deshalb nicht erneut erzeugt.

**15 reale API- und 8 reale MCP-Prüfungen dieses Images bestanden**: alle
vorherigen 14/7 sowie Grasovka 8,99 €, 500 ml, 17,98 €/l, ohne Bonuspreis. Ein
erster Lauf brach an einer falschen Erwartung des Prüfskripts ab (Anzeigeformat
„500 ml“ statt „500ml“); er wird nicht als bestanden gezählt. Die MCP-Antwort
nennt die Punkte nicht; die API führt sie unter `offer_condition`.

Vier-Regionen-Loader-Lauf desselben Images, kein Quellcode-Overlay, temporärer
DNS nur im Wegwerfcontainer:

| PLZ | importierte Datensätze | Dauer | sichtbare Einschränkungen |
|---|---:|---:|---|
| 26135 | 4022 | 41,5 s | kein passender offizieller REWE-/Marktkauf-Markt; ein Marktguru-Timeout (Getränke); ALDI Süd, Globus, Netto schwarz, trinkgut ohne Markt |
| 10115 | 3454 | 75,0 s | kein Marktkauf-Markt; EDEKA-Marktanzeige nicht abgeglichen; zwei Marktguru-Timeouts |
| 50939 | 3954 | 70,7 s | ein Marktguru-Timeout (Saft); trinkgut 73 statt 72, keine unlesbare Karte |
| 04109 | 4093 | 19,8 s | EDEKA-Marktanzeige nicht abgeglichen; HOL’AB! ohne Markt |

Die höhere Leipziger Zahl gegenüber dem Lauf von `ddd47d6` (4021) stammt aus
PENNY 309 statt 238 ohne Marktguru-Teilausfall in diesem Lauf, nicht aus einer
Codeänderung. Zwei optionale KaufDA-Globus-Bildabrufe lieferten HTTP 404.
Importmengen sind keine Aussage über Prospektvollständigkeit.

Unverändert offen: strukturierte Hirsch-Details bei Lidl (`UPSTREAM_MISSING`),
ungeklärte Globus-ab-Gruppen, ALDI-Süd-Prospekt unter dem normalen Host-DNS
(`SOURCE_UNAVAILABLE`, nur mit temporärem öffentlichem DNS geprüft), fehlende
exakte Märkte in einzelnen PLZ, Drittanbieter-Timeouts sowie die mit
`NOT_VERIFIED` markierten Filial- und Datumsabgleiche. Es gab keine produktive
Installation und kein neues signiertes APK-Release.

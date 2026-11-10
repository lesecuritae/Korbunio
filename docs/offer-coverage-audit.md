# Händler-Angebotsabdeckung

Stand: 10.11.2026. Ausgangsrevision: `1479643ff66bc54184ff9cdca27b5f1247ce2635`
(0.1.75). **Arbeitsstand, keine vollständige Abnahme und kein Release.**

## Verfahren und Aussagegrenzen

Das Backend registriert 19 Händler. Android besitzt 18 eigenständige native
Provider; Marktkauf ist bisher über den Server erreichbar. Die vollständige
Stichprobenliste steht in [offer-coverage-samples.json](offer-coverage-samples.json):
112 dokumentierte Beobachtungen für alle 19 Händler, darunter ausdrücklich
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
| REWE `rewe` | nativ / ja | offiziell; Marktguru/KaufDA bei Fehler | Köln, Berlin, Leipzig | 5; —/—/— | `SOURCE_UNAVAILABLE`: direkte Referenzabrufe 403; regionaler Prospekt vorhanden, konkrete Marktgeltung offen. Native Metadaten/Preisrundung korrigiert. |
| ALDI Nord `aldi-nord` | nativ / ja | offiziell + kontrollierter KaufDA-Ortsprospekt | Berlin 10115 | 5; 0→5 / 0→5 / 0→5 in regionalem Replay | `UPSTREAM_MISSING`: Viba, Riesa, Eberswalder, Ileburger und Mühlhäuser fehlen im offiziellen Standardfeed, im eigenen Berlin-Prospekt vorhanden. Ergänzung bei gefülltem Katalog getestet. Live-Gesamtabnahme offen. |
| ALDI Süd `aldi-sued` | nativ / ja | offizielle Webangebote/strukturierter Wochenprospekt | Köln; separater temporärer DNS-Gegentest | 5 Produktseiten + 5 echte Prospektdatensätze; 151 Prospektimporte | `SOURCE_UNAVAILABLE` im normalen NextDNS-Testnetz; mit temporärer öffentlicher Auflösung HTTPS und Parser erfolgreich. Kein TLS-Bypass oder produktiver DNS-Wechsel. |
| Lidl `marktguru-lidl` | nativ / ja | Marktguru + regionaler KaufDA-Viewer | Leipzig, Köln | 5; 5/5/5 Grundstichprobe | `CACHE_STALE`/partielle Quellabrufe und Varianten-Suchlücke behoben; Hirsch-Metadaten `UPSTREAM_MISSING`; weitere Dublettenprüfung offen. |
| PENNY `marktguru-penny` | nativ / ja | Marktguru | Leipzig | 5; 5/5/5 Backwaren | `PARSER_LOSS`: 1.000 g wurde 1 g; expliziter „ohne App“-Preis ergänzt. Donnerstag-Toniebox als Vorschau vorhanden. Weitere Produktgruppen offen. |
| Netto Marken-Discount `netto-marken` | nativ / ja | Marktguru, bestehende Filialwahl | Leipzig | 5; 5/5/5 Name/Preis | `PARSER_LOSS`: ausdrücklich „NETTO APP“ ohne „PLUS“ wurde nicht erkannt; korrigiert. Nicht auf Cashback als Barpreis anwenden. |
| Netto schwarz `netto-schwarz` | nativ / ja | offiziell; vorhandener Marktguru-Fallback | Berlin, Leipzig | 5 Prospektartikel; Filialgeltung —/—/— | Filialsuche aus öffentlichem eingebettetem Store-JSON repariert, 31 Live-Angebote; spezifische Händlerzuordnung vor generischem Netto. Prospektstichprobe noch `NOT_VERIFIED`. |
| Kaufland `kaufland` | nativ / ja | offiziell, filialspezifisch | Köln-Ehrenfeld 4130, Thebäerstraße 9 | 5; 5/5/5 Name/Preis/Pack | Filialadresse unabhängig bestätigt und passend zum regionalen Prospekt. Unabhängige Mitgliedspreis-/Folgewoche-Abnahme offen (`NOT_VERIFIED`). |
| EDEKA `edeka` | nativ / ja | offizieller ausgewählter Markt, moderne HTML-Angebote vor Legacy-API | Köln Romano 070696/12145; Berlin/Leipzig Legacy | 9 reale Dialoge im Vertrag, 224 live | `PARSER_LOSS`: Legacy verlor App-Preise. Reguläre/App-Preise, Pfand, GTIN und Packung aus marktgebundener HTML-Seite; 220/220 bestehende IDs eindeutig weiterverwendbar. Kein fremder Markt als Ersatz. |
| Marktkauf `marktkauf` | Servermodus / ja | offizieller Marktadapter + eigene Markt-HTML für fehlende Mengen | Markkleeberg; Frechen | 5; 5/5/5 Name/Preis, nun 5/5 Mengen | `PARSER_LOSS`/Quellenlücke: Philadelphia 100–195 g aus derselben offiziellen Wochenkarte ergänzt. Nur fehlende, eindeutig zuordenbare Mengen; keine Preis-/Datumsüberschreibung. |
| Globus `globus` | nativ / ja | offizieller Markt-/Faltblattadapter; bestehende Bild-Ergänzung | Köln, Leipzig | 5 beobachtet; —/—/— unabhängig | Native Gültigkeitsdaten und Beschreibung übernommen. Vollständiger unabhängiger Referenzabgleich offen (`NOT_VERIFIED`). |
| famila Nordwest `marktguru-famila-nordwest` | nativ / ja | Marktguru | Oldenburg 26135 | 5; 5/5/5 Name/Preis/Pack | `PARSER_LOSS`: explizite MOIN-CARD-Preise erkannt. Prospekt nennt beim 14.11. falschen Wochentag; keine künstliche Datumsänderung. Weitere Region offen. |
| aktiv & irma `aktiv-irma` | nativ / ja | offizielle Wochen-HTML-Seite | Oldenburg 26135; 26122 negativ | 5 offizielle Karten; 5/5/5 | `DATE_REGION_FILTER`: „gültig ab Donnerstag“ wurde Wochenmontag zugeordnet; produktspezifische Korrektur und Tests ergänzt. |
| Combi `marktguru-combi` | nativ / ja | Marktguru | Oldenburg 26135 | 5; 5/5/5 Namen/Preise | MOIN CARD korrigiert. Prospekt-Varianten 140/150 g bzw. zwei Kistengrößen sind nicht vollständig im Rohdatensatz ausformuliert (`UPSTREAM_MISSING`/Variantenprüfung offen). |
| HOL’AB! `holab` | nativ / ja | offizielle ausgewählte Wochen-HTML-Angebote | Oldenburg 26135 | 5 Karten; 5/5/5, Mengen nach Korrektur | `PARSER_LOSS`: Liter-Schreibweisen und Zwei-Kisten-Preis; 4,49 € ab 2, ausdrücklich 4,99 € einzeln, 8,98 € für 2. Hemelinger-Kisten bleiben Alternativen statt Summenpack; Pfand/Grundpreis ohne Variantenwahl nicht eindeutig. Kein Anspruch auf ganzen Prospekt. |
| trinkgut `trinkgut` | nativ / ja | Backend offiziell; Android Marktguru/KaufDA | Köln; andere Testregionen ohne nahen Markt | 5 Produktseiten; Namen/Preise vorhanden, regionale Enddaten — | Öffentliche Produktseite nennt 13.11., ausgewählter Feed 14.11.; Marktgeltung vor Klassifizierung prüfen (`NOT_VERIFIED`). Kein Preis aus anderem Markt übernehmen. |
| Rossmann `rossmann` | nativ / ja | offiziell gerendert; vorhandene Fallbacks | Docker-Chromium; regionale Filialgeltung offen | 24 reale offiziell gerenderte Angebote | Quelle im Docker erreichbar. Alte Spielwarenreferenzen belegen keine allgemeine Filialgeltung; unabhängige Fünf-Artikel-/Filial-Abnahme bleibt `NOT_VERIFIED`. |
| Müller `mueller` | nativ / ja | datierter eigener KaufDA-Händlerprospekt; kein allgemeiner Sale-Ersatz | reale PLZ-Koordinaten; Filialgeltung ausdrücklich offen | 7 veröffentlichte Artikel im Vertrag; 89 live | `PARSER_LOSS` behoben: Sortiment nicht länger als Wochenangebote. Eigener Herausgeber, Datierung und App-Preis geprüft; örtlicher Bestand `NOT_VERIFIED`. |
| dm `dm` | nativ / ja | offizielle Ausverkaufs-API | Online; Leipzig/Köln | 5 API-Beobachtungen; Detailseiten-Challenge | `PARSER_LOSS`: native Mengen und Server-Nullwerte korrigiert. 401 beobachtete Ausverkaufsangebote; deklarierte Gesamtzahl und fehlende letzte Seite geprüft. Detailseiten weiterhin `SOURCE_UNAVAILABLE`. |

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

**Noch offen:** abschließende Referenz-/Dublettenvergleiche, die in der Tabelle
benannten Rohdaten-/Regionsnachweise, weitere unabhängige Händler-/Regionsnachweise und anschließender Git-Abschluss
mit Push/PR/CI und bestätigtem Merge. Der hier getestete Code ist lokal committet;
ein Push, Merge oder produktives Release hat noch nicht stattgefunden. Die produktive Installation
wurde für die Diagnose lesend abgefragt; die Test-Images sind keine bereits
veröffentlichte oder produktiv ausgerollte Version.

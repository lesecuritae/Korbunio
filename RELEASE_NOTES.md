# 0.1.11

Die Android-App bietet jetzt dieselbe freie Händlerauswahl wie die
KorbKlar-Weboberfläche. Die gewählten Händler bleiben lokal gespeichert und
werden bei der nächsten Angebotssuche automatisch wieder verwendet.

Die lokale Einkaufsliste ist nun auch direkt aus der Angebotsübersicht
erreichbar. Damit lassen sich gespeicherte Artikel während der Suche und beim
Vergleichen jederzeit öffnen, ohne zur Startseite zurückzugehen.

# 0.1.10

KorbKlar 0.1.10 liefert die Android-App erstmals mit einer dauerhaften
Release-Signatur aus. Künftige APK-Aktualisierungen können dadurch installiert
werden, ohne die lokal gespeicherten App-Daten zu verlieren.

Eigene KorbKlar-Server lassen sich jetzt sicher mit der App koppeln: Ein
Admin-API-Key erzeugt einmalig einen getrennten App-Token, dessen Klartext nur
im sicheren Android-Speicher liegt. Der Server speichert ausschließlich einen
Hash. Die App bietet außerdem eine ausdrückliche Auswahl zwischen System-,
heller und dunkler Darstellung.

dm ist über den offiziellen, frei erreichbaren Ausverkaufskatalog als Händler
verfügbar. KorbKlar zeigt dabei ausschließlich tatsächlich gekennzeichnete
Ausverkaufsartikel und weist transparent darauf hin, dass Onlinepreise keine
Filialverfügbarkeit zusichern. Eine Erläuterung in der Ergebnisansicht macht
zudem deutlich, dass grüne Preise den günstigsten direkt vergleichbaren Preis
und keine allgemeine Preisbewertung kennzeichnen.

Die direkte KitchenOwl-Anbindung wurde zusätzlich gegen eine laufende
KitchenOwl-Instanz geprüft: Anmeldung, Listenerkennung sowie Übergabe und
Rücklesen der Angebotsinformationen funktionieren mit der aktuellen API.

# 0.1.9

KorbKlar 0.1.9 ergänzt einen eigenständigen Android-Client. Ein eigener
KorbKlar-Server lässt sich in der App konfigurieren; bereits geladene Angebote
und die lokale Einkaufsliste bleiben auch ohne Serververbindung verfügbar.

Die App kann die Postleitzahl nach Zustimmung aus dem Gerätestandort ermitteln,
speichert dabei aber keine GPS-Koordinaten. KitchenOwl lässt sich optional
direkt anbinden. Zugangstoken liegen ausschließlich im sicheren Android-Speicher
und werden über unverschlüsselte Verbindungen nicht übertragen.

# 0.1.8

KorbKlar 0.1.8 löst HOL’AB!-Märkte anhand der tatsächlich angefragten PLZ auf.
Damit werden regionale Angebote beispielsweise für 21423 korrekt dem Markt
Winsen/Luhe zugeordnet, statt vom voreingestellten Kartenausschnitt der
Marktseite abhängig zu sein.

In den Ergebnissen lassen sich mehrere Händler per Umschalt-Klick gemeinsam
auswählen. Händlerauswahl, Kategorie und Sortierung bleiben lokal im Browser
gespeichert. Eigene Schlagwortfilter sind nun direkt unter „Filter und
Sortierung“ aktivierbar und werden in einem separaten Dialog verwaltet.

Produktbilder in der Einkaufsliste bleiben in einem festen Bildrahmen. Dadurch
ragen insbesondere ALDI-Süd-Bilder nicht mehr in benachbarte Artikelzeilen.
Zusätzlich verwendet die ALDI-Süd-Prospektprüfung wieder durchgängig das
vorgegebene Referenzdatum.

# 0.1.7

KorbKlar 0.1.7 ergänzt eine optionale Auswahl zwischen aktueller Angebotswoche
und Folgewoche. Direkte Händlerquellen werden – soweit technisch verfügbar –
gezielt für die Vorschauwoche geladen. Fehlt die Vorschau bei einem Händler,
bleibt dessen aktueller Bestand sichtbar und die Oberfläche weist transparent
auf den Fallback hin. Wochen besitzen getrennte Cache-Schlüssel; ältere
Snapshots mit abweichender Angebots- oder Pfandsemantik werden nicht erneut
verwendet.

Persistente Schlagwortfilter prüfen ausschließlich Produktnamen mit
ODER-Verknüpfung. Sie lassen sich im Browser hinzufügen, bearbeiten und
löschen sowie in einem versionierten JSON-Format exportieren und importieren.
Leere und doppelte Einträge werden bereinigt, fehlerhafte Dateien verständlich
abgewiesen.

Der strukturierte ALDI-Süd-Prospekt übernimmt jetzt vorhandene Marken und
artikelbezogene Produktbilder vollständig. Pfand wird zentraler und
quellengerecht behandelt: veröffentlichte Gesamtpfandwerte von Lidl, Netto,
ALDI Nord und weiteren Quellen werden nicht erneut multipliziert; ausdrücklich
je Behälter ausgewiesenes ALDI-Süd-Pfand wird für das Verkaufsgebinde summiert.
Bei Mehrwegkästen können getrennt veröffentlichte Flaschen- und
Verpackungspfandanteile addiert und transparent dargestellt werden. Ein bereits
als Gesamtwert veröffentlichter Kastenpfand wird nicht mehr fälschlich als
gleichmäßiger Einzelpfand pro Flasche ausgegeben.

# 0.1.6

KorbKlar 0.1.6 repariert die Filialauflösung für Orte, deren exakte
REWE-Märkte auf unterschiedlichen Orts- und Bundeslandseiten veröffentlicht
werden. Exakte Treffer werden anhand der numerischen Markt-ID zusammengeführt,
dedupliziert und vollständig zur manuellen Auswahl angeboten; die gewählte
Filiale wird weiterhin lokal gespeichert. Für Leipzig liefert die offizielle
Quelle damit wieder beide exakten Märkte statt nur des auf der Stadtseite
gelisteten Centers.

Die Ladeanzeige bezeichnet ihre Einheiten nun eindeutig als technische
Datenquellen. Ihre Gesamtzahl wird aus dem tatsächlichen Ladeplan einschließlich
später notwendiger Fallback- oder Bildläufe gebildet. Backend und Oberfläche
stellen zusätzlich sicher, dass der verarbeitete Zähler nie größer als die
Gesamtzahl dargestellt wird.

Noch nicht konfigurierte zukünftige ALDI-Süd-Prospekte gelten nicht mehr als
Fehler eines erfolgreichen aktuellen Abrufs. Der strukturierte aktuelle
Wochenprospekt bleibt unverändert Primärquelle; Preis, Grundpreis, Pfand,
artikelbezogenes Bild und Gültigkeitszeitraum bleiben getrennt. Die kompakte
Marktanzeige der Ergebnisse erhält einen direkten Weg zurück zur Änderung.

Der Markt-Audit unterscheidet bewusst filialadressierbare Quellen von regionalen
Katalogen: Lidl veröffentlicht für den geprüften Leipziger Bereich mehrere nahe
Filialen, aber keinen exakten Markt unter der eingegebenen PLZ; Marktguru liefert
zudem keine Filial-ID für eine belastbare Angebotszuordnung. Daher wird keine
wirkungslos erscheinende Lidl-Filialauswahl vorgetäuscht.

# 0.1.5

KorbKlar 0.1.5 behebt die unvollständige ALDI-Süd-Erfassung und verbessert die
Bedienung der Ergebnisansicht. Der strukturierte offizielle ALDI-Süd-Prospekt
ist nun die vollständige Primärquelle; dadurch erscheinen auch Lebensmittel,
Obst und Gemüse, die auf der bisherigen Angebotsseite fehlten. Verkaufspreis,
Grundpreis, ausdrückliches Pfand und artikelbezogenes Bild bleiben getrennt.
ALDI Nord verwendet weiterhin seinen offiziellen Angebotsdatensatz und
übernimmt daraus nun auch das ausdrückliche strukturierte Pfandfeld. Bei
ALDI-Süd-Mehrfachgebinden wird das je Behälter ausgewiesene Pfand auf das
Gesamtpfand des Verkaufspacks hochgerechnet und zugleich transparent je
Behälter und als Packsumme angezeigt.

Die Marktanzeige zählt nur tatsächlich auswählbare, deduplizierte REWE-Märkte.
Händler- und Bonusauswahl werden nach der Suche platzsparend eingeklappt,
bleiben aber jederzeit änderbar. Nicht notwendige Sticky-Bereiche wurden
entfernt, damit der mobile Seitenfluss keine Inhalte oder Touch-Ziele verdeckt.
Die ausgewählten konkreten Filialen werden kompakt im Ergebnis angezeigt.

Die README-Dateien enthalten keine duplizierte Release-Historie mehr; diese
Datei ist die einzige chronologische Release-Quelle. Versionsgebundene interne
Zwischenberichte wurden aus dem öffentlichen Repository entfernt und aktuelle
Funktionen, Händlerpfade, Einkaufsliste und Exportgrenzen wurden dokumentiert.

# 0.1.4

KorbKlar 0.1.4 korrigiert die Bildauswahl des offiziellen Globus-Adapters.
Vollständige Prospekt-, Vorschau- und PDF-Seiten werden nicht mehr als
Produktbilder gespeichert. Der Adapter verwendet ausschließlich ein explizit
am Artikel hinterlegtes Produkt- oder Einzelangebotsbild; liefern die
offiziellen Daten – wie derzeit – nur Seitenbilder, bleibt das Produktbild
bewusst leer.

Die Snapshot-Generation wurde gezielt erhöht, damit bereits gespeicherte
Globus-Angebote mit falschen Seitenbildern nicht erneut ausgeliefert werden.
Der URL-abhängige binäre Bildcache und sämtliche anderen Laufzeitdaten bleiben
erhalten. Die Bildpfade von REWE, Kaufland, ALDI, EDEKA/Marktkauf, Rossmann und
Müller wurden ebenfalls auf ihre Artikelbindung geprüft.

Da Globus derzeit keine separaten Artikelbilder liefert, dürfen KaufDA und
danach Marktguru für Globus ausnahmsweise nur die Bild-URL eines einzelnen
Angebots ergänzen. Das geschieht ausschließlich
bei einer eindeutigen Übereinstimmung von Produktname, Preis, Packung und
Zeitraum; Angebotsdaten, Händlerquelle und Links bleiben offiziell. Mehrdeutige
oder abweichende Treffer bleiben ohne Bild. Im Live-Test am 28. August wurden
für PLZ 93073 sechs eindeutige KaufDA-Bilder mit 477 offiziellen Angeboten
verknüpft. Marktguru lieferte für die geprüften Globus-Märkte keine Datensätze.

ALDI-Süd-Karten unterscheiden jetzt Verkaufspreis, Grundpreis, durchgestrichenen
Altpreis und Pfand, bevor eine echte Mehrproduktkarte aufgeteilt wird. Dadurch
werden weder Pfand noch Grundpreise als Artikelpreis oder Produktname erfasst.
Die app-spezifische Bring-Übergabe wurde entfernt; allgemeines Web Share,
Textkopie, TXT und JSON bleiben erhalten. Für KitchenOwl ist eine getestete,
netzwerkfreie Adaptergrenze passend zum offiziellen `name`-/`description`-Schema
vorbereitet. Zugangsdaten oder API-Tokens werden nicht in KorbKlar gespeichert.

# 0.1.3

KorbKlar 0.1.3 priorisiert konkrete Produktmerkmale vor Händler- und
Quellkategorien. Dadurch werden unter anderem CLEANMAXX Bodenkehrer,
MÄLZER&FU Ice Cream und FUNNY-FRISCH Pom-Bär korrekt eingeordnet.
Geschmacksangaben wie „Franzbrötchen“ überschreiben die eigentliche Produktart
nicht mehr. Abweichungen werden intern mit Quellkategorie, erkannter Kategorie
und `category_conflict` nachvollziehbar protokolliert.

Ein Audit vorhandener Angebotssnapshots deckt weitere Konflikte bei Rucola,
Katzenfutter, Süßwaren, Backwaren, Reinigern und Eisprodukten auf und sichert sie
mit Regressionstests ab. Die Cache-Generation wurde angehoben, damit alte
Kategorisierungen nicht erneut ausgeliefert werden.

Die vorhandene native Windows-Einrichtung und die
portable Erkennung von Chromium, Chrome und Edge bleiben unverändert erhalten.
Die doppelte Startseiten-Auswahl „ALDI in deiner Nähe“ entfällt; ALDI Nord und
ALDI Süd werden weiterhin direkt über die Händlerauswahl gesteuert.

# 0.1.2

KorbKlar 0.1.2 präzisiert die Pfandanzeige für Mehrfachgebinde. Beim BLACK-CAT-Energy-Viererpack wird jetzt ausdrücklich „0,25 € je Dose · 1,00 € gesamt für 4“ angezeigt. Der Gesamtpfandwert des Verkaufspacks bleibt für Warenkorb und Einkaufsliste erhalten; eine einzelne Dose wird weiterhin mit 0,25 € Pfand geführt. Die Projektdokumentation enthält außerdem eine freiwillige Monero-Unterstützungsmöglichkeit; KorbKlar bleibt ohne Spende vollständig kostenlos und uneingeschränkt nutzbar.

# 0.1.1

KorbKlar 0.1.1 führt „Netto schwarz“ als eigenständigen Händler neben Netto Marken-Discount ein. Die offizielle Netto-Angebotsseite liefert reguläre Wochenangebote und öffentlich ausgewiesene Netto+-Mitgliederpreise. Die offizielle Marktsuche ordnet eine exakte PLZ bevorzugt zu und begrenzt den Nächstmarkt-Fallback auf 15 km. Beide Netto-Unternehmen und ihre Programme bleiben technisch getrennt; persönliche Coupons, Stempelkarten und nicht bezifferte Vorteile werden nicht geschätzt.

Mitgliederpreise ohne veröffentlichten regulären Vergleichspreis werden nur bei aktivierter Mitgliedschaft gezeigt und niemals als regulärer Verkaufspreis umetikettiert. REWE Bonus bleibt eine Gutschrift, während veröffentlichte App-/Kartenpreise als bedingte Kassenpreise modelliert werden. PAYBACK-Punkte und persönliche Coupons werden weiterhin nicht pauschal in Euro umgerechnet.

Der explizite Marktguru-Pfandtext des Netto-Markendiscount-Angebots „BLACK CAT Energy Drink“, einschließlich der Schreibweise `zzgl. Pfand 1.–`, wird als separater Pfandbetrag übernommen. Aus einer bloßen Dosen- oder Getränkeangabe wird weiterhin kein Pfand geraten. Die Cache-Generation wurde angehoben, damit ältere unvollständige Angebotsabbilder nicht wiederverwendet werden.

Rossmann ist über die offizielle gerenderte Angebotsseite angebunden; ausschließlich ausdrücklich als „Aus der Werbung“ markierte Karten gelangen mit Preis, Grundpreis, Bild, Link und Werbezeitraum in den Vergleich. Müller liefert seine offiziellen Online-Angebote direkt aus der strukturierten Produktliste. Diese bleiben ausdrücklich als Online-Angebote gekennzeichnet und werden nicht als lokaler Filialpreis ausgegeben.

Kaufland verwendet bevorzugt die offizielle filialbezogene Verfügbarkeits-JSON zusammen mit den strukturierten Angebotsdaten der Wochenübersicht. Regulärer Preis und Kaufland-Card-XTRA-Preis bleiben getrennt; XTRA wird nur bei ausgewähltem Programm als bedingter Preis berücksichtigt. Der bisherige Browserabruf bleibt als Kompatibilitätsfallback erhalten.

Die bestehende browserlokale Einkaufsliste kann offene Artikel über allgemeines Web Share oder die Zwischenablage weitergeben. Eine dezente freiwillige Unterstützungssektion ergänzt die Startseite ohne Popup, Werbung oder Tracking.

Das Laufzeitimage verwendet eine gepinnte Python-3.13-Alpine-Basis. Damit wird die bisherige Debian-Basis ersetzt, nachdem der Release-Scan dort nicht reparierte kritische Betriebssystem-Findings gemeldet hatte.

# 0.1.0

KorbKlar 0.1.0 erweitert den Vergleich um eine gespeicherte Händlerauswahl und eine manuelle REWE-Filialauswahl bei mehreren exakten PLZ-Treffern. Die Vergleichs-API akzeptiert optional `retailers`; jede Händler- und REWE-Marktauswahl erhält einen getrennten Cache-Schlüssel.

Globus wird über den offiziellen Markt- und Prospektdatenstrom geladen. Für PLZ 93073 wird der Markt Neutraubling aufgelöst; die offizielle Quelle gewinnt vollständig, Marktguru dient nur bei Fehlern oder leeren offiziellen Daten als ungemischter Fallback.

ALDI-Süd-Karten mit mehreren separat bepreisten Produkten werden in einzelne Angebote aufgeteilt, ohne Zeitraum oder Dublettenlogik zu verlieren. REWE-Bonusgutschriften bleiben vom Verkaufspreis getrennt und erscheinen beispielsweise als „+ 0,50 € REWE Bonus“, ohne Preis- oder Grundpreisranking zu verfälschen.

Die reproduzierbare Suite umfasst 207 bestandene Tests. Live geprüft wurden Globus Neutraubling (477 Angebote), die REWE-Mehrmarkt-PLZ 26123 einschließlich manueller Auswahl sowie Kaufland 44791. Die Startseite wurde bei 390×844, 412×915 und 1440×1000 geprüft. Issue #8 bleibt für den nicht reproduzierbaren historischen Kaufland-Datensatz, eine frei wählbare Datumsspanne und zusätzliche Händler offen.

# 0.0.7

KorbKlar 0.0.7 integriert die geprüften Änderungen aus dem Fork von Claudia Dietrich:

- Native Windows-Einrichtung mit lokal gebundener Anwendung und automatischer Suche nach Chromium, Chrome oder Edge. Linux- und Docker-Aufrufe verwenden dieselbe portable Browserauflösung.
- Ein bewusster Schalter auf der Startseite kann den Angebotscache für eine Suche umgehen. Ohne Auswahl bleibt das bisherige Cacheverhalten unverändert.
- Die exakten Leverkusener PLZ 51371, 51373, 51375, 51377, 51379 und 51381 sind anhand offizieller ALDI-Süd-Filialnachweise ergänzt. Es wird weiterhin keine Präfixschätzung verwendet.
- HTTPS-Verbindungen behalten Zertifikats- und Hostnamenprüfung bei und verwenden zusätzlich den reproduzierbaren certifi-Vertrauensspeicher; lokale Systemzertifikate werden weiterhin ergänzt.
- Explizite Euro-Beträge aus REWE-Zusatztexten wie „MIT APP 0,10 € REWE BONUS“ werden bei ausgewähltem REWE Bonus korrekt vom effektiven Preis abgezogen. Prozent-, Punkte- oder unbezifferte Vorteile werden nicht geschätzt.

Die browserlokale Einkaufsliste, Combi/famila Nordwest, die getrennten ALDI-Regionen, Containerhärtung und GHCR-Veröffentlichung bleiben unverändert erhalten.

# 0.0.6

KorbKlar 0.0.6 erweitert den versionierten, PLZ-genauen offiziellen ALDI-Regionsnachweis für Aachen, den Kreis Düren, den nördlichen Kreis Heinsberg, Mülheim an der Ruhr, Duisburg-Walsum und Dorsten. Die Zuordnung verwendet keine pauschale `52xxx`- oder Präfixregel. Unbekannte PLZ bleiben dem begrenzten Standort-Fallback vorbehalten; Gummersbach und Siegen bleiben ausdrücklich als Grenzfälle mit beiden Regionen erhalten. Auf der Startseite kann der Nutzer die automatische Erkennung optional durch „ALDI Nord“, „ALDI Süd“ oder „Nord und Süd“ ersetzen; die Auswahl wird bis in den getrennten regionalen Quellenabruf weitergereicht.

# 0.0.5

KorbKlar 0.0.5 behebt zwei Datenverluste auf dem Weg vom Angebot in die browserlokale Einkaufsliste:

- Das bereits abgesicherte lokale Bildproxy-Ziel wird im kanonischen IndexedDB-Modell gespeichert und als Produktbild in der Einkaufsliste dargestellt. Es bleibt nach Reload sowie im JSON-Backup erhalten. Fremde, direkte oder ausführbare Bildziele werden nicht gerendert.
- Ausdrücklich von ALDI, REWE oder Marktguru veröffentlichte Pfandbeträge werden in das Angebotsmodell übernommen, getrennt als Integer-Cent gespeichert und mengenabhängig in Position, Händlergruppe und Gesamtsumme eingerechnet. Aus Verpackungsbezeichnungen wie „Dose“ oder „Flasche“ wird kein Pfandwert geraten.

Die übrigen Hinweise aus Issue #8 – insbesondere der ohne ungeschwärzte PLZ und Filialangabe nicht reproduzierbare REWE-/Kaufland-Fall sowie zusätzliche Featurewünsche – bleiben getrennt dokumentiert und werden nicht als erledigt ausgegeben.

# 0.0.4

Revision: Zenq & Enzo

KorbKlar 0.0.4 korrigiert die Verarbeitung der offiziellen ALDI-Süd-Wochenangebote. Gültigkeiten werden nun mit der Priorität Produktkarte, Angebotsgruppe und Wochenzeitraum ermittelt. Montag-, Donnerstag-, Freitag-/Samstag- und weitere ausdrücklich genannte Aktionstage bleiben dadurch erhalten.

Der Abruf verwendet das bereits vorhandene gehärtete Browserprofil von `curl_cffi`. Alte Vorwochen, redundante Themenansichten und parallele Kategorieparser werden nicht mehr zu einem gemischten Bestand vereinigt. Die angebotsbezogene Deduplizierung bevorzugt einen präzisen Zeitraum gegenüber einer groben Wochenangabe, behält aber echte Preis-, Packungs- und Zeitraumvarianten. Lose Ware mit der Schreibweise „Preis €/1 kg“ wird ebenfalls vollständig erfasst.

Combi und famila Nordwest ergänzen als optionale regionale Händler die bestehende Marktguru-Schiene. Eine leere regionale Antwort ist kein Quellenfehler; die dokumentierte Abdeckung kann je PLZ unterschiedlich sein. famila Nordost ist als eigenständige Handelsgruppe ausdrücklich von der Zuordnung ausgeschlossen. Angebote beider neuen Händler lassen sich ohne Sondermodell in die lokale Einkaufsliste übernehmen.

# 0.0.3

- ALDI behandelt bestätigte Regionen und die Grenzstädte Gummersbach/Siegen ohne PLZ-Präfix-Heuristik.
- HOL’AB! ist über die offizielle Markt- und Angebotsseite integriert. Pfand, Mengenbedingungen und Teilabdeckung bleiben sichtbar getrennt.
- 18 einheitliche deutsche Kategorien, getrennte Produkt-/Quelllinks, REWE-Deeplinks und ehrliche offizielle Lidl-Suchfallbacks.
- Zugängliche Bild-Lightbox, lokales KorbKlar-Hintergrundmotiv und automatisches helles/dunkles Farbschema.
- Browserlokaler Bereich „Einkauf“ mit IndexedDB, manuellen Artikeln, Mengensteuerung, Abhaken, Händlergruppen und rundungssicherer Cent-/Pfandberechnung.
- Lokaler Text-/Messenger-Import und -Export, TXT, Web Share sowie versioniertes JSON-Backup mit Vorschau und Größenlimit; keine persönlichen Listendaten erreichen den Server.
- Kanonisches Listenmodell mit Adaptergrenze für mögliche spätere KitchenOwl-/Grocy-Anbindungen, ohne Sync oder neue externe Abhängigkeit.

Die damaligen Auditdetails bleiben in der Git-Historie nachvollziehbar; im aktiven Quellstand wird nur der aktuelle Sicherheitsbericht mitgeführt.

---

# 0.0.2

## Neue Funktionen

- Serverseitig verwalteter Suchauftrag mit echtem Fortschrittsbalken, Prozentwerten, Statusphasen, aktiver Quelle, Händler, Kategorie, Verarbeitungsschritt sowie Quellen- und Produktzähler.
- Kategorieauswahl anhand der von Händler beziehungsweise Quelle gelieferten Warengruppen; Kategorien sind außerdem direkt an jedem Produkt sichtbar.
- Dezenter, rein CSS-basierter Desktop-Hintergrund ohne zusätzliche Downloads; auf kleinen Bildschirmen wird er deaktiviert.

## Behobene Fehler

- Der große dynamische Ergebnis-Kopf bleibt mobil nicht mehr sticky. Filter, Bonusprogramme und Händlernavigation blockieren dadurch weder Scrollen noch Touch-Bedienung.
- Händler- und Dubletten-Chips sind mobil horizontal bedienbar, ohne den Dokument-Scroll einzuschließen oder Inhalte zu überlagern.
- Lidl-Angebote aus Marktguru öffnen eine stabile Lidl-Quellseite bei Marktguru statt einer teilweise fehlerhaften pauschalen Lidl-Zielseite.
- Datumsabhängige Parser-Tests verwenden nun einen expliziten Bezugszeitpunkt und laufen nicht nach Ablauf der damaligen Angebotswoche rot.

## Technische Änderungen

- Versionsmetadaten auf `0.0.2` vereinheitlicht.
- Jobstatus ist in einer gekapselten, begrenzten Backend-Komponente untergebracht; Ergebnisdaten bleiben unverändert im persistenten SQLite-Snapshot-Cache.
- Docker-Image mit aktuellem Python-3.13-Bookworm-Base-Image und den beim Build verfügbaren Debian-Sicherheitsupdates neu gebaut.
- Keine unnötigen Major-Upgrades; die bestehenden kompatiblen Dependency-Bereiche wurden beibehalten und beim Image-Build frisch aufgelöst.

## Testergebnisse

- 110 Unit-/Integrations- und Regressionstests bestanden, 8 optionale Live-Tests in der Standardausführung übersprungen.
- Reale Suche für PLZ 01067 im Release-Container abgeschlossen: 1.708 Angebote von sieben Händlern und 248 Quellkategorien.
- Healthcheck, persistenter Cache, Loader-Statusfolge, Ergebnis-API, Kategorieausgabe und Lidl-Ziel-URL im Container geprüft.
- Mobile Viewports 390 × 844 sowie Desktop 1440 × 1000 mit Chromium geprüft.

---

# 0.1.0 (historischer Entwicklungsstand)

Lizenz: BSD-3-Clause. Copyright (c) 2026 lesecuritae für Tarnkappe.info.

KorbKlar ist die überarbeitete Ausgabe des bisherigen Supermarkt-Preisvergleichs. Die Vergleichslogik und die bestehenden Quellenadapter bleiben erhalten; Name, Oberfläche und öffentliche Projektmetadaten wurden auf KorbKlar umgestellt.

## Änderungen

- Neues KorbKlar-Branding für Weboberfläche, Favicon und README-Grafik.
- Docker-Dienst, Container und Daten-Volume tragen den neuen Namen `korbklar`.
- Python-Paketmetadaten und User-Agent wurden auf KorbKlar aktualisiert.
- Native Installationen verwenden für neue Laufzeitdaten `~/.local/state/korbklar`; ein vorhandener alter Zustandspfad wird automatisch weiterverwendet.
- Dunkles Farbschema an die grüne KorbKlar-Farbwelt angepasst.
- README- und SVG-Branding bereinigt; die Header-Grafik kommt ohne problematische SVG-Filter aus.
- Bestehende Preis-, Mengen-, Marken-, Händler-, Bild- und Cache-Regressionstests bleiben erhalten.

## Docker-Hinweis beim Umstieg

Durch den neuen Compose-Projektnamen und das neue Volume `korbklar-data` wird ein bestehendes Docker-Volume der alten Ausgabe nicht automatisch eingebunden. Darin liegen nur Laufzeitdaten wie Snapshots, Signierschlüssel und Bildcache. Für einen frischen Start kann das alte Volume unangetastet bleiben; bestehende signierte Ergebnislinks gelten dann nicht im neuen Volume weiter.

---

# 0.0.1

Lizenz: BSD-3-Clause. Copyright (c) 2026 lesecuritae für Tarnkappe.info.

Erster öffentlicher GitHub-Stand des Supermarkt-Preisvergleichs.

## Enthalten

- Browseroberfläche mit Postleitzahl als einzigem Pflichtfeld.
- Direkte Händleradapter für REWE, EDEKA, Kaufland, Marktkauf und ALDI.
- Regionale Marktguru-Daten für Lidl, PENNY, Netto und GLOBUS sowie händlerspezifische Fallbacks.
- Sonntagsauswahl der kommenden Angebotswoche; Kaufland berücksichtigt seinen Donnerstag-bis-Mittwoch-Zyklus.
- Persistenter 24-Stunden-Cache für die Kaufland-Filialzuordnung und den gesetzten Browserzustand. Die Angebote selbst werden weiterhin frisch abgerufen.
- Persistenter 24-Stunden-Cache für die REWE-Marktauswahl; Angebotsdaten bleiben davon getrennt und werden frisch geladen.
- Ergebnisansicht mit Reiter zum Einblenden teurerer Dubletten; die Anzahl bezieht sich auf den aktuellen Text- und Händlerfilter.
- Normalisierung von Packungsgrößen und Grundpreisen; alternative Größen werden als Alternativen dargestellt und nicht addiert.
- Platzhalter wie `This is no brand` werden nicht als Marke angezeigt oder für den Produktabgleich verwendet. Auch Varianten mit angehängter Quell-ID wie `thisisnobrand123` werden verworfen.
- REWE-Fußnoten in Produkttiteln, etwa die Backstation-Markierung `²`, werden nicht mehr als Bestandteil des Produktnamens übernommen.
- Bei Auswahl genau eines Händlers wird die redundante Händlerspalte in der Ergebnisliste ausgeblendet.
- Bonusprogramme, Produktfilter, Sortierung und Endless Scroll.
- Persistenter Ergebnis- und Bildcache im Daten-Volume sowie signierte Ergebnis- und Bildlinks.
- Optionaler REST-Endpunkt und optionaler API-Key.
- Konfigurationswerte werden bei ungültigen Integer-Werten auf sichere Defaults und Grenzen zurückgeführt, statt den Dienst beim Import zu beenden.

## Betrieb

Die Standardinstallation besteht aus einem Anwendungscontainer auf Port 8000. Laufzeitdaten liegen ausschließlich im Docker-Volume beziehungsweise unter dem konfigurierten Datenpfad und gehören nicht ins Repository.

## Dokumentation

- Installation, Architektur und Abhängigkeiten sind im README beschrieben.
- Geplante spätere Integrationen mit Grocy und KitchenOwl sind als Roadmap gekennzeichnet.
- Die Tarnkappe.info-Spendenseite und die aktuell veröffentlichte Monero-Adresse sind im README verlinkt.

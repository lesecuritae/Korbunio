# Händler-Challenges

Einige Händler schützen ihre öffentlichen Seiten mit einer JavaScript- oder
CAPTCHA-Prüfung. Korbuino versucht diese Prüfung nicht automatisch zu lösen
und deaktiviert weder TLS noch den Schutzmechanismus.

## Android-App

Wenn ein direkter Abruf mit `403`, `429` oder einer Challenge fehlschlägt,
öffnet die App die offizielle Händlerseite in einem eingebetteten WebView.
Der Nutzer öffnet die Seite selbst und tippt bei Müller anschließend auf
„Müller-Angebote übernehmen“. Die App übernimmt dafür das sichtbare,
clientseitig gerenderte HTML-Dokument einmalig und parst es lokal; dadurch
funktioniert der Abruf auch dann, wenn die Hintergrundanfrage eine leere
Shell oder `403` erhält. Händler-Cookies bleiben im geschützten WebView-
Cookie-Store und werden nicht an den Server, in Korbuino-Backups oder die
Room-Datenbank übertragen.

## Docker-Webbetrieb

Der Hintergrundprozess läuft in einem separaten Container und kann Cookies aus
dem Browser des Nutzers nicht heimlich lesen. Bei einer Müller-Challenge zeigt
die Ergebnisansicht deshalb einen Link zur offiziellen Müller-Seite. Danach
kann der Nutzer den Cookie-Header der Müller-Domain ausdrücklich über die
angezeigte Session-Seite übergeben. Korbuino hält ihn nur kurz im
Arbeitsspeicher, sendet ihn ausschließlich an Müller und löscht ihn bei Ablauf
oder einer erneuten Challenge. Er landet nicht in SQLite, Backups, Logs oder
API-Antworten.

Ein unbeaufsichtigtes Umgehen der Challenge ist nicht Teil von Korbuino. Für
einen dauerhaften Serverabruf ist ein offizieller Müller-Endpunkt oder eine
ausdrücklich erlaubte Schnittstelle erforderlich.

# Händler-Challenges

Einige Händler schützen ihre öffentlichen Seiten mit einer JavaScript- oder
CAPTCHA-Prüfung. Korbuino versucht diese Prüfung nicht automatisch zu lösen
und deaktiviert weder TLS noch den Schutzmechanismus.

## Android-App

Wenn ein direkter Abruf mit `403`, `429` oder einer Challenge fehlschlägt,
öffnet die App die offizielle Händlerseite in einem eingebetteten WebView.
Der Nutzer bestätigt die Prüfung selbst. Danach liest der direkte OkHttp-
Abruf die von der WebView gesetzten Händler-Cookies und versucht den Provider
erneut. Die Cookies werden nicht in Korbuino-Backups oder der Room-Datenbank
gespeichert.

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

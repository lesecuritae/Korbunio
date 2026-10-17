# KitchenOwl in der nativen Android-App

Unter **Einstellungen → KitchenOwl** die HTTPS-Adresse der gewünschten Instanz
angeben. Die Verbindung funktioniert direkt vom Android-Gerät aus; ein
Korbuino-Server oder MCP ist dafür nicht erforderlich.

Beispiele:

- Offizieller Dienst: `https://app.kitchenowl.org`
- AdminForge: `https://kitchen.adminforge.de`
- Eigene Instanz: deren HTTPS-Adresse, gegebenenfalls einschließlich Unterpfad.

## Benutzerkonto

**Benutzerkonto** auswählen, den KitchenOwl-Benutzernamen oder die E-Mail-Adresse
und das dortige Passwort eingeben und **Verbinden** antippen. Danach die
gewünschte Haushalts-/Einkaufsliste wählen.

Die App verwendet die KitchenOwl-API (`POST /api/auth`, anschließend
`POST /api/auth/llt`) und erhält einen eigenen dauerhaften Token mit dem
Gerätenamen **Korbuino Android**. Nur dieser Token und die Serveradresse werden
im vorhandenen verschlüsselten Android-Speicher abgelegt. Das Passwort wird
weder gespeichert noch exportiert. Die temporäre Login-Sitzung wird anschließend
nach Möglichkeit widerrufen. Dauerhafte Tokens lassen sich in KitchenOwl unter
den Sitzungen beziehungsweise Zugangstokens widerrufen.

Das funktioniert mit eigenen und gehosteten Instanzen, sofern ein lokales
KitchenOwl-Passwort vorhanden und die Passwortanmeldung erlaubt ist. Ein
AdminForge-SSO-Konto hat nicht automatisch ein lokales KitchenOwl-Passwort.
Ein vorgeschalteter SSO-Login wird nicht mit fremden Zugangsdaten automatisiert.

## Bestehender Token / SSO

Alternativ **Token** wählen und einen in KitchenOwl angelegten dauerhaften Token
eintragen. Das ist auch der Weg für Konten, die sich ausschließlich per SSO
anmelden. Die vorhandene Token-Anbindung und bestehende Verbindungen bleiben
kompatibel. Ohne konfigurierte Verbindung erfolgen keine KitchenOwl-Anfragen.

Es werden keine Benutzerkonten erstellt. Fehlgeschlagene Anmeldungen ersetzen
keine bereits gespeicherten Zugangsdaten. HTTP-Adressen, Zugangsdaten in URLs
und HTTP-Weiterleitungen werden abgelehnt; die endgültige HTTPS-Adresse eingeben.

## English summary

In Android settings, select your KitchenOwl HTTPS server and either **Benutzerkonto**
(username/email and password) or **Token**. Hosted services and self-hosted servers
use the same API. Password login exchanges the password for a device-specific,
revocable long-lived token stored in Android encrypted preferences. The password
is not saved or exported. SSO-only accounts must use a KitchenOwl token. Neither
a Korbuino server nor MCP is required.

## API reference

The login and long-lived-token endpoints follow the [official KitchenOwl API](https://docs.kitchenowl.org/dev/reference/API/).
Public capability checks on 2026-10-17 returned backend version 124 for both
`app.kitchenowl.org` and `kitchen.adminforge.de`, without the password-login-disabled
flag. AdminForge additionally advertises an OIDC provider.

## Verification boundary

Automated tests use a TLS-enabled MockWebServer, including login, long-lived-token
exchange, temporary-session revocation, authenticated list discovery, rejected
credentials, missing tokens, malformed responses, redirects and rate limits.
Public server capability checks do not establish that a particular user's account
supports password login; that requires their own account and an interactive test.

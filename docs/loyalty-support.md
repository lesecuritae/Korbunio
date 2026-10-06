# Bonusprogramme / Loyalty support

## Deutsch

Die Auswahl- und Preislogik sowie die strukturierte API-/Android-Übertragung
sind für alle zwölf registrierten Programme geprüft. Das bedeutet nicht, dass
jede Händlerquelle alle persönlichen Coupons oder Punkte veröffentlicht.

| Programm | Öffentliche Quelldaten und Grenzen |
| --- | --- |
| REWE Bonus | Konkretes Euro-Guthaben aus REWE-Badges; kein niedrigerer Kassenpreis. Native Quelle und Server haben Parser-Tests. |
| Lidl Plus | Konkrete regionale Plus-/App-Preise über Marktguru; native Parser-Tests vorhanden. |
| PENNY App | Konkrete regionale App-Preise über Marktguru; native Parser-Tests vorhanden. |
| Netto plus App | Öffentliche App-Preise; Euro-Guthaben wird serverseitig gesondert erkannt. Der native HTML-Import liefert derzeit keine Bonusmetadaten, der Marktguru-Fallback kann konkrete Mitgliedspreise liefern. |
| Netto+ (Netto schwarz) | Serverseitiger Filialparser trennt App- und Normalpreis. Der native HTML-Import liefert derzeit keine Bonusmetadaten. |
| Kaufland Card XTRA | Separate XTRA-Preisfelder aus der offiziellen Filialquelle; native und Server-Parser-Tests vorhanden. |
| EDEKA App | Serverseitig konkrete App-Preise aus Angebotsbeschreibung; der native EDEKA-Direktimport liefert derzeit keine Bonusmetadaten. |
| MARKTKAUF App | Konkrete öffentliche App-Preise aus Angebotsbeschreibung, wenn die verwendete Quelle sie liefert. |
| mein GLOBUS | Marktguru kann konkrete Mitgliedspreise liefern; der native Erstquellen-Prospektimport liefert derzeit keine Bonusmetadaten. |
| PAYBACK | Konkrete veröffentlichte Produktvorteile; keine pauschale Umrechnung von Punkten oder persönlichen Coupons. |
| ROSSMANN-App | Prozent-Coupons ohne konkreten resultierenden Produktpreis werden nicht berechnet. Kein allgemeiner Coupon-Abgleich mit einem Kundenkonto. |
| Müller Blüten | Keine pauschale Umrechnung von Blüten oder persönlichen Coupons; erforderlich ist ein konkreter veröffentlichter Euro-Vorteil. |

**Server-Modus:** Ab 0.1.59 gelangen alle vom Server erkannten Vorteile in die
native App. Mehrere Programme pro Angebot bleiben getrennt wählbar. Ältere
Server ohne `benefits` bleiben nutzbar, liefern der App aber keine Bonusauswahl.
Ein Update allein erzeugt keine Coupon-Daten, die die Quelle nicht veröffentlicht.

**Tests:** `tests/test_loyalty.py` prüft sämtliche registrierten IDs in API und
Auswahllogik; `ServerProviderTest` prüft den Android-Import, Mehrfachvorteile und
vollständige Pagination. `LoyaltySelectionTest` trennt Kassenpreis und Guthaben.
`test_android_loyalty_migration.py` prüft vorhandene Daten und Room-Schema.
Diese Regressionstests sind keine zwölf Live-Anmeldungen bei Kundenkonten.

## English

All twelve registered program IDs are covered by selection, API and native
Android import tests. Public source coverage differs: REWE euro credits,
Kaufland XTRA fields and regional Lidl/PENNY/member-price data have dedicated
parsers. Native HTML imports for the two Netto brands, the native EDEKA import
and the native Globus leaflet import currently do not carry loyalty metadata;
the server mode can supply benefits its own parsers recognize.

Cashback stays separate from checkout and price ranking. Points, percentage-only
discounts and personal coupons are not converted into invented product prices.
Version 0.1.59 preserves multiple server benefits per offer and allows separate
selection. Older servers remain compatible but cannot supply this metadata.
Regression coverage does not imply authenticated live access to twelve customer
accounts or universal availability of public member prices.

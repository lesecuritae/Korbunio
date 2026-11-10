# Offer coverage fixtures

Minimal public-response excerpts captured 2026-11-09/10; fixed test date is
2026-11-09. They contain published offer fields, not runtime credentials.
Full raw responses and flyer images are intentionally excluded from Git.

- `marktguru_kania.json`: public offer 25583947, Kania Wildgerichte, 400 g,
  €3.99; UTC dates deliberately differ from the Berlin calendar dates.
- `marktguru_mayonnaise.json` / `marktguru_gulaschsuppe.json`: actual Lidl
  public/member price pairs; expiry remains the published expiry, not extended
  to make a live search pass.
- `kaufda_kania.json`: Leipzig Lidl viewer 2501324792, including its published
  Wildschweingulasch category. A category is retained only when it extends the
  actual product name; it cannot create a different animal/product variant.
- `kaufda_lidl_plus.json`: selected actual price deals from the Cologne viewer
  2501324797, with conditional and regular prices kept separate.
- `kaufda_variants.json`: actual multi-product deal associations and different
  duvet sizes/prices from a Lidl regional viewer.
- `kaufda_aldi_regional.json`: five selected products from Berlin ALDI Nord
  viewer 2501318401, absent from the inspected default official catalogue.
- `marktguru_moin_contract.json` / `marktguru_netto_app_contract.json`:
  normalized public fields from the Oldenburg/Leipzig responses, used as wording
  contracts, not raw transport-response fixtures.
- `holab_selected.html`: five minimal public offer cards plus published validity
  metadata from https://holab.de/angebote; the two-crate condition and explicit
  single-crate price are preserved.

Tests mutate copies for simulated failures, foreign retailers, expiry, variants,
filled catalogues and unknown prices. Those mutations are not live product facts.
Passing fixtures does not establish national or complete leaflet coverage.

- `mueller_mixed_listing.html`: the first five actual Drogerie category cards,
  reduced to names/SKUs/prices/badges. Exactly three carry Sale and two are
  ordinary assortment. Category membership and UVP alone must not qualify.
- `aktiv_selected.html`: five actual weekly cards, including the product-local
  “gültig ab Donnerstag” restriction. It must not inherit Monday from its tab.
- `kaufda_mueller_brochure.json`: seven actual products from dated Müller
  publisher viewer 2501311481 (02–14 November). The explicit Müller app price
  remains separate; the global publisher does not establish branch stock.
- `edeka_romano_offers.html`: nine minimal offer dialogs from the selected
  official market page https://www.edeka.de/maerkte/070696/angebote/ including
  normal/app prices and different GTINs with identical titles. Tracking prices
  alone are not evidence of the unconditional cash price.
- `marktkauf_quantity.html`: the selected Markkleeberg weekly Philadelphia
  offer's published quantity; used only for exact, missing-field enrichment.
- `aldi_sued_published_products.json`: five minimal actual product objects from
  https://prospekt.aldi-sued.de/kw46-26-op-mp/ (09–14 November), captured on
  10 November using an operator-authorized, process-local public DNS test.
  TLS verification remained enabled. No resolver override ships in the app.
- `netto_black_integer_price.html`: the actual Trefl Spielesammlung card from
  https://netto.de/angebote/ captured 10 November, with the published `8.–`
  whole-euro price and weekly dates. This is not an inferred missing decimal.
- `rossmann_published_cards.html`: five actual advertised products from the
  official rendered weekly page, 09–13 November, including coffee, hair care,
  household paper, baby wipes and hair colour. The separately published toy
  leaflet is not treated as evidence for general branch assortment.
- `netto_black_app_price.html`: the actual advertised Müllermilch card has
  an app price of €0.59 and separately labelled per-litre prices; it does not
  publish a normal checkout price. Neither an upper bound nor rounded unit
  pricing is converted into an invented normal price.
- `netto_black_stores.html`: three minimal real store rows out of the 338
  entries in the official `initialStores` Flight catalogue. The excerpt tests
  parsing and distance logic; it does not itself prove nationwide absence.
  An optional private full-catalogue replay and separately recorded live
  Berlin/Oldenburg lookups provide the broader operational evidence.

- `globus_published_prices.json`: six minimal published Köln-Marsdorf article
  records from the official KW46/2026 `pageitems.json`. The official cover
  independently shows the five food offers and the 9–14 November validity.
  The pan record explicitly binds three diameters to three prices. `mgprice`
  denotes the separately published mein GLOBUS price; ranges are retained.

- `rewe_public_include.json`: minimal first-party rendered/included card fields
  for selected market 1940016, captured 10 November 2026. One missing NAN was
  explicitly requested through the published frontend-includes endpoint; request
  correlation IDs are generated by tests. The optional full 188-card transport
  capture stays outside Git and is replayed only when an operator supplies it.

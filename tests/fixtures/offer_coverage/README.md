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

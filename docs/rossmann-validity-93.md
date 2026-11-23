# Rossmann: missing catalogue validity (#93)

The source required a catalogue-wide date banner before reading any product card.
Two renders without that banner therefore rejected usable advertised products.
Android had the same requirement and only recognized the older banner wording.

The parser now retains explicitly advertised cards with their published prices,
packs and article numbers when the banner is absent. ISO dates remain absent;
the visible validity label and coverage note say that validity is unconfirmed.
Android carries this warning in source diagnostics and each offer description.
An undated Android catalogue cannot establish a next-week preview. The backend
retains its existing next-week fallback warning. Coupon footnotes are not global
offer periods. Recognizable malformed or reversed banners still fail, as do
challenge pages without readable advertised cards. Existing cache lifetimes and
offline retention are unchanged: an unconfirmed offer is not a guarantee that a
price remains valid, and users must check the retailer.

## Evidence, 2026-11-23 UTC

- Before the fix, both new missing-banner/broken-render regression tests failed.
- A fresh, isolated Playwright Chromium session rendered the official offers URL:
  24 product elements, 22 advertised readable offers, published period
  2026-11-23 through 2026-11-27. The reported missing banner was not present as a
  live defect on this date.
- Replaying that captured DOM with only the global banner removed retained all
  22 offers, with absent ISO dates and explicit unconfirmed-validity labels.
  This replay is a controlled test, not a second live-source observation.
- The application's direct Chromium dump invocation timed out on this host;
  a plain HTTP request returned a shell with no cards. Neither is counted as a
  successful live application/Docker fetch. No production deployment was made.

Tests cover missing banners, coupon footnotes, source identity and prices,
non-advertised/challenge pages, malformed and reversed dates, year boundaries,
late banners, retained API-response/MCP validity, Android current/next-week
behaviour, and the newer Android date wording. Run:

```sh
pytest -m 'not live'
cd android
./gradlew testStandardDebugUnitTest testFdroidDebugUnitTest assembleStandardDebug assembleFdroidDebug
```

No product prices or dates were added to production code. Revert the fix commit
to restore the prior strict rejection policy; no database migration is required.

# Public Kaufland bundle fixture

`kaufland-de5220-multibuy-20261015.json` is the unchanged offer object
`ART.483431_KAV.3693303` extracted from public OfferTemplate props.offerData.cycles.
It describes K-WINTER EDITION Adventskalender, 3 packs for EUR 3.00, each 75 g.

- URL: https://filiale.kaufland.de/angebote/uebersicht.html?kloffer-week=current
- Request cookie: `x-aem-variant=DE5220`
- Retrieved: 2026-10-15T16:33:24.722402+00:00
- Original response SHA-256: `a37515e0587958752556fddc6599f1c6f283aaf84c805efa0ba01ae56571d166`
- Source selling period: salesFrom 2026-10-12, salesTo 2026-10-17.

This is evidence for the real public `bbyMessage` shape. It is not an Em-eukal
capture. Em-eukal cases in OfferPricingTest use synthetic domain data.
`bonusbuy` also marks loyalty offers; it does not establish a quantity condition.
`formattedOldPrice` does not establish a current price for one pack.
`bbyNo` does not establish permission to mix different products.

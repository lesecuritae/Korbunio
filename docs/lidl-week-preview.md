# Published offers later in the current week

A live read-only MCP query for Coca-Cola at Lidl returned
no offers on 19 October 2026. The regional source already supplied offer
25301467: six 0.33-l containers, EUR 3.99 plus EUR 1.50 deposit, valid
22–24 October. Its UTC start (21 October 22:00Z) is 22 October in Berlin.

The server discarded it while mapping source rows because validity meant
valid today, whereas the UI selects the current week. Select periods
overlapping the remaining selected week instead. Retain the original
validity label and instruct MCP clients to state it, so Thursday previews
are not described as today's prices. Expired and next-week periods remain
excluded; Sunday continues to select the upcoming Monday.

Snapshot schema v12 prevents old, already-filtered caches from hiding the
fix. No credentials, source endpoints, shopping lists, or retailer routing
are changed. This fixes the regional aggregator pipeline; first-party
retailer adapters keep their existing validity rules.

Regression tests cover the real offer's dates and price, Berlin time and
the October DST transition, expired periods, next-week exclusion, and
source-to-offer mapping.

The native Android Marktguru adapter selects the same remaining-week window
and retains the brand in searchable product names. Server-mode imports now
retain validity dates as well; the existing shopping planner keeps future
prices out of today's totals. No database schema or permission changes.

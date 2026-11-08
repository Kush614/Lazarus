# LAZARUS evidence report

## Seal
- heldout_hash: `35d544ddda162806b5d42c45b63b8d68d074de93a94ac624e062d005c13ca511`
- memo: `LAZARUS-SEAL src:148eaaad7fdf3cdffa67275362b3b630e1b17daee6aa637b271c750b5abf98f9 ho:35d544ddda162806b5d42c45b63b8d68d074de93a94ac624e062d005c13ca511`
- network: `fetchai-stable-testnet (dorado-1)`
- source_hash: `148eaaad7fdf3cdffa67275362b3b630e1b17daee6aa637b271c750b5abf98f9`
- timestamp: `2026-11-07T06:22:49.645308+00:00`
- tx_hash: `7A3C8BE99C0A78365C4F6A13EC769EFFA7FE5844535C1D1A274F794742E6A9D8`
- wallet: `fetch1h35fm8faj9790adzt7cfdkks67yezcwqrta067`

## Observed
Each of these has a recorded trace behind it.

- **H-0001** `/healthz` GET /healthz returns 200 with body {"ok": true, "version": "3.11.2"} on every call (seq 2,16,33,34,37,45,47,52,58,72,75,86,87,90,98,100,108,116,124,126,142,145,146,158,163,167,173,174,182,189,205,206,217,224,225,231,241,252,260,269,275,276,290,292,294). (traces: T-0001)
- **H-0003** `/sku` GET /sku/{unknown} returns 404 with body {"error":"unknown sku"} e.g. /sku/NOPE seq6, /sku/QQ-9 seq105, /sku/ZZ-1 seq181, /sku/XX-0 seq194. (traces: T-0004)

## Inferred
These are guesses. No probe has settled them, so do not rely on them.

- **H-0002** `/sku` GET /sku/{known} returns 200 with catalog mapping: AX-200->{Anchor bolt, 20mm, 249}, FX-12->{Fixing kit, 615}, EN-1->{Enclosure, IP65, 12995}, DR-44->{Drill bit set, 4999}, JB-1000->{Junction box, 88888}, CL-9->{Clamp, large, 777}, BR-310->{Bracket, steel, 1899}, GS-8->{Gasket, rubber, 45}, AX-100->{Anchor bolt, 10mm, 125}, BR-320->{Bracket, aluminium, 1450}, HN-55->{Hinge, heavy duty, 2105}, CL-7->{Clamp, small, 333}. (confidence 0.98)
- **H-0004** `/invoice` POST /invoice subtotal_cents equals sum(qty*unit_cents) from request items, e.g. seq4 3*4999+11*12995=157942, seq35 1*777+7*777+7*249+12*777=17283, seq176 2*125+5*333+8*12995=105875. (confidence 0.98)
- **H-0005** `/invoice` POST /invoice total_cents equals subtotal_cents - discount_cents + tax_cents, e.g. seq176 105875-5000+6617=107492, seq3 116955-0+7017=123972, seq40 827031-0+59960=886991. (confidence 0.98)
- **H-0006** `/invoice` POST /invoice with region OR charges tax_cents 0 regardless of subtotal/date, e.g. seq5 37523->0, seq11 21050->0, seq12 234260->0, seq39 67044->0, seq49 519425->0. (confidence 0.96)
- **H-0007** `/invoice` POST /invoice region FL charges 6% tax rounded to nearest cent, e.g. seq3 116955->7017, seq7 814727->48884 (814727*0.06=48883.62), seq14 19887->1193, seq46 51544->3093. (confidence 0.92)
- **H-0008** `/invoice` POST /invoice region WA charges 6.5% tax rounded to nearest cent, e.g. seq4 157942->10266, seq9 22169->1441, seq20 17290->1124, seq74 216018->14041. (confidence 0.92)
- **H-0009** `/invoice` POST /invoice region TX charges 6.25% tax rounded to nearest cent, e.g. seq35 17283->1080, seq102 88231->5514, seq117 84025->5252, seq125 2997->187. (confidence 0.92)
- **H-0010** `/invoice` POST /invoice region NY charges 8.88% tax rounded to nearest cent, e.g. seq15 13050->1159, seq31 8420->748, seq48 1008460->89551, seq56 32390->2876. (confidence 0.90)
- **H-0011** `/invoice` POST /invoice region CA rate changed over time: ~7.25% for invoice dates in 2021-2023 e.g. seq80 2022-05-26 41437->3004, seq85 2021-02-07 9363->679, seq91 2023-02-13 36246->2628, seq295 2021-11-26 289670->21001, and ~8.25% for dates in 2024-2026 e.g. seq65 2024-11-15 15449->1275, seq68 2024-07-10 95370->7868, seq144 2025-06-17 301811->24899; most likely cutover at 2024-01-01 but log does not show exact boundary (latest 7.25% is 2023-10-03 seq118, earliest 8.25% is 2024-05-18 seq113). (confidence 0.65)
- **H-0012** `/invoice` POST /invoice with header X-Legacy-Mode:1 forces 7.25% tax regardless of region/date, e.g. seq40 CA 2025-03-14 827031->59960 (vs 8.25% expected 68230) and seq94 NY 2024-05-11 14894->1080 (vs 8.88% expected 1323). (confidence 0.68)
- **H-0014** `/invoice` POST /invoice coupon matching is exact: coupon "save10 " (lowercase with trailing space) is treated as unknown, giving discount 0 and warnings ["unknown_coupon"], e.g. seq3 FL 116955 discount 0 warnings unknown_coupon. (confidence 0.75)
- **H-0016** `/rate` POST /rate non-USD conversions use fixed factors per pair, e.g. GBP->MXN ~21.635 (seq61 643823->13929110, seq198 147253->3185818), GBP->CAD ~1.72888 (seq122 843573->1458453, seq152 817711->1413740), CAD->MXN ~12.513 (seq29 291481->3647593, seq138 730148->9137072), CAD->USD ~0.73119 (seq76 775620->567133, seq147 49078->35885), JPY->CAD ~0.009099 (seq21 81210->739, seq111 316329->2878), MXN->CAD ~0.07990 (seq51 421100->33645, seq139 609537->48702), EUR->JPY ~162.625 (seq236 116905->19012260, seq238 289051->47008364). (confidence 0.85)

## Refuted
These were believed, then disproved by a trace.

- **H-0013** `/invoice` POST /invoice coupon SAVE10 exact uppercase gives discount_cents 5000 with empty warnings, e.g. seq176 date 2026-01-27 TX subtotal 105875 discount 5000 tax 6617 total 107492; tax is computed on full subtotal (105875*0.0625=6617) not subtotal-discount. (traces: T-0037)
- **H-0015** `/rate` POST /rate USD conversions use fixed factors: USD->MXN ~17.114 (e.g. seq1 642518->10996695, seq8 683823->11703630, seq62 439045->7514255), USD->EUR ~0.9213 (seq26 332923->306721, seq44 349432->321931), USD->CAD ~1.3677 (seq27 337205->461195, seq218 44560->60944), USD->JPY ~149.834 (seq70 310548->46529406, seq129 125557->18812205), USD->GBP ~0.79107 (seq71 223478->176793, seq106 766023->606000). (traces: T-0039)

## Port versions
Scores are on sealed tests no agent can read.

| Version | Score | Regressions | Status | Decided by |
|---|---|---|---|---|
| v1 | 50.5% | 0 | ADOPTED | auto |
| v2 | 51.0% | 0 | ADOPTED | auto |
| v3 | 44.5% | 13 | ROLLED_BACK | auto |

## How the method improved

- no changes yet

## Divergences

- **D-0001** on port v1, GET /healthz/, bounty tx: none
- **D-0002** on port v1, GET /sku/AX-200/, bounty tx: none
- **D-0003** on port v1, GET /sku/JB-1000/, bounty tx: none
- **D-0004** on port v1, GET /sku/REFUTE-0001/, bounty tx: none
- **D-0005** on port v1, POST /invoice/, bounty tx: none
- **D-0006** on port v1, POST /invoice/, bounty tx: none
- **D-0007** on port v1, POST /invoice/, bounty tx: none
- **D-0008** on port v1, POST /invoice/, bounty tx: none
- **D-0009** on port v1, POST /invoice/, bounty tx: none
- **D-0010** on port v1, POST /invoice/, bounty tx: none
- **D-0011** on port v1, POST /invoice/, bounty tx: none
- **D-0012** on port v1, POST /invoice/, bounty tx: none
- **D-0013** on port v1, POST /invoice/, bounty tx: none
- **D-0014** on port v1, POST /invoice/, bounty tx: none
- **D-0015** on port v1, POST /invoice/, bounty tx: none
- **D-0016** on port v1, POST /invoice/, bounty tx: none
- **D-0017** on port v1, GET /sku/AX-100/, bounty tx: none
- **D-0018** on port v1, POST /invoice/, bounty tx: none
- **D-0019** on port v1, POST /invoice/, bounty tx: none
- **D-0020** on port v1, POST /invoice/, bounty tx: none
- **D-0021** on port v1, POST /invoice/, bounty tx: none
- **D-0022** on port v1, POST /invoice/, bounty tx: none
- **D-0023** on port v1, POST /invoice/, bounty tx: none
- **D-0024** on port v1, POST /invoice/, bounty tx: none
- **D-0025** on port v1, POST /invoice/, bounty tx: none
- **D-0026** on port v1, POST /invoice/, bounty tx: none
- **D-0027** on port v1, POST /invoice/, bounty tx: none
- **D-0028** on port v1, POST /invoice/, bounty tx: none
- **D-0029** on port v1, POST /invoice/, bounty tx: none

## Verified payments
Only transfers the chain confirmed are recorded here.

- none

Failures logged during this run: 0
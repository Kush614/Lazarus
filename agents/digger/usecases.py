"""Where this could go. Illustrative: only the demo relic has a build behind it."""
HTTP = "HTTP service: same shape as this demo"
ADAPTER = "Needs a new adapter first"

USE_CASES = [
    {"id": "billing", "title": "Billing nobody can read", "fit": HTTP, "problem": "The invoicing engine still runs, but the source is lost and every change is a gamble.",
     "digs": "Tax, discount and rounding rules, from its real responses.", "get": "A maintained port, plus a score against tests it never saw."},
    {"id": "vendor", "title": "Vendor went under", "fit": HTTP, "problem": "A product you paid for still runs, with no patches and no one to call. Check its licence first.",
     "digs": "The working API contract, including routes the manual never listed.", "get": "A replacement you own, with each behaviour traced to a probe."},
    {"id": "acquired", "title": "Inherited service", "fit": HTTP, "problem": "An acquisition left you a service whose team and documents are gone.",
     "digs": "What each endpoint actually does, as opposed to what people recall.", "get": "A ledger of proven behaviour that new engineers can trust."},
    {"id": "rewrite", "title": "Prove a rewrite is safe", "fit": HTTP, "problem": "You rewrote it already, and nobody will sign off the cutover.",
     "digs": "Sealed tests from the old system, and hunters paid to catch differences.", "get": "A list of divergences, each with the input that reproduces it."},
    {"id": "spec", "title": "Recover the spec", "fit": HTTP, "problem": "You want the documentation, and don't need a port at all.",
     "digs": "Claims sorted into proven, guessed and refuted.", "get": "A spec where every line links to the trace behind it."},
    {"id": "hidden", "title": "Map hidden routes", "fit": HTTP, "problem": "You need to know what a system you own really exposes. Only for systems you are authorised to test.",
     "digs": "Undocumented routes, limits and legacy switches.", "get": "An inventory of behaviour missing from the docs."},
    {"id": "firmware", "title": "Device with no source", "fit": ADAPTER, "problem": "A gateway or controller answers on the network, and its firmware source is gone.",
     "digs": "Its protocol behaviour, through an adapter that would have to be built.", "get": "A software twin to test against without touching hardware."},
    {"id": "audit", "title": "Tamper-evident evidence", "fit": HTTP, "problem": "Someone has to show the tests weren't edited after seeing the results.",
     "digs": "Hashes of the source and test set, sealed on-chain before the work.", "get": "A public timestamp anyone can check against the reveal."},
]

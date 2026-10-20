# External decision set: jev-bench banking77 subset

Source: `Praveenrajus/jev-bench` on Hugging Face (JevBench-style System One
decision set; banking77 configs; underlying data `mteb/banking77`,
license cc-by-4.0 (PolyAI; mirror: mit)). Downloaded 2026-10-20.

Construction: the 10 most frequent banking77 intents in the test split
(card_arrival, getting_spare_card, verify_my_identity, passcode_forgotten,
transfer_into_account, visa_or_mastercard, card_linking, pending_top_up,
beneficiary_not_allowed, age_limit), 100 rows each = 1000 rows. The test split
holds only 183 rows for these intents, so the pool draws test first, then
validation, then train (no model training happens in this benchmark, so split
mixing does not leak). Criteria are trimmed to the 10 selected intents so the
choice primitive fits the 10-option cap of the Quyet encoder API. Fixed seed
20261020. Each row keeps the original jev-bench `id`, `state`, `label`, and a
rewritten `question` (typed choice, same shape as our lanes).

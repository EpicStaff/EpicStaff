### Condition blocks

[Role & Objective]
Explain the deciding part of one rule — the test, and everything that follows once it passes — in
business terms, prioritizing routing outcomes over implementation quirks.

[Field-by-Field Rules]
1. `expression` & `field_expressions` — the test. Combine with AND and describe the resulting check
   once, in business terms. They often restate each other — a quirk of how the table is edited, not
   two separate checks. Both empty means the rule always matches — say so outright.
2. `order` & `enabled` — place the rule in the queue. Mention what runs before it only when it
   matters (a rule near the bottom is reached less often than the reader may assume).
3. `on_match.prompt` — the AI prompt that runs when the rule matches. Name it; its own block
   explains what it asks.
4. `on_match.sets_variables` — whether the rule changes stored values on match. Say that it does;
   the assignments block says what changes.
5. `on_match.goes_to` — where the work goes when this rule matches. This is usually the sentence the
   reader most came for — do not bury it.
6. `continue_after_match` — matters only when `goes_to` is empty. With a destination, the table
   stops regardless of this setting. Without one, and continue off, the rule matches, does its work,
   and hands over to the table's default destination.
7. `on_no_match` — what happens when the test fails: on to the next rule, or out to the default
   destination if this was the last rule that could have matched.
8. `route_code` — the outgoing connector label only. You may name it as such; never present it as a
   reason the work goes anywhere.

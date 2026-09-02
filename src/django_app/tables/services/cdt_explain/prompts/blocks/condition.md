### Condition blocks

A condition block is the deciding part of one rule: the test, and everything that follows from the
test passing.

- `expression` and `field_expressions` are the test. Combine them with **and** and describe the
  resulting check once, in business terms. They often say the same thing twice — that is a quirk of
  how the table is edited, not two separate checks. Both empty means the rule always matches, which
  is worth saying outright.
- `order` and `enabled` place the rule in the queue. Mention what is checked before it only when it
  matters — a rule near the bottom is reached less often than the reader may assume.
- `on_match.prompt` names an AI prompt that runs when the rule matches. Name it; the prompt's own
  block explains what it asks.
- `on_match.sets_variables` tells you the rule changes stored values when it matches. Say that it
  does; the assignments block says what changes.
- `on_match.goes_to` is where the work goes when this rule matches. This is the sentence the reader
  most often came for, so do not bury it.
- `continue_after_match` matters **only when `goes_to` is empty**. When there is a destination, the
  table stops regardless, and saying otherwise is wrong. When there is no destination and continue is
  off, the rule matches, does its work, and then hands over to the table's default destination.
- `on_no_match` says what happens when the test fails: on to the next rule, or out to the default
  destination because this was the last rule that could have matched.
- `route_code` is the connector label only. You may name it as the outgoing connector. Never present
  it as a reason the work goes anywhere.

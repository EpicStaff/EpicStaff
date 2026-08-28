### Assignment blocks

Assignments run when the rule has matched, after its AI prompt if it has one. They change stored
values that later rules and later steps can read.

- `assignments` and `field_assignments` both set values, and both run. Describe them together as one
  set of changes rather than as two mechanisms.
- Say **what each value becomes**, in plain terms — a queue set to a named team, a priority set to a
  number, a reason recorded as text. Naming the value and its new setting is the whole job here.
- When a new value is worked out from existing ones, say what it is derived from. Do not walk
  through the arithmetic.
- These changes persist beyond the rule. Where a later rule in the table tests a value this block
  sets, that link is worth a clause — it is exactly the kind of invisible connection the reader
  cannot see on the diagram.
- Nothing here affects where the work goes. Assignments and destinations are separate; do not imply
  a value being set causes any routing.
- If both fields are empty the rule changes nothing when it matches, and saying so is a complete
  explanation.

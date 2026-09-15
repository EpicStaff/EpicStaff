### Assignment blocks

[Role & Objective]
Explain what a rule's assignments change once it has matched, focusing on outcome and downstream
dependency rather than mechanism.

[Field-by-Field Rules]
1. Timing & scope — assignments run after the rule matches, and after its AI prompt if it has one.
   The values they set persist beyond the rule: later rules and later steps can read them.
2. `assignments` & `field_assignments` — both set values, and both run. Describe them together as
   one set of changes, not two mechanisms. Say what each value becomes in plain terms — a queue set
   to a named team, a priority set to a number, a reason recorded as text.
3. Derived values — when a new value is worked out from existing ones, say what it is derived from.
   Do not walk through the arithmetic.
4. Downstream dependencies — where a later rule in the table tests a value this block sets, that
   link is worth a clause; it is exactly the kind of connection invisible on the diagram.
5. Routing — nothing here affects where the work goes. Assignments and destinations are separate;
   never imply that setting a value causes routing.
6. Empty case — if both fields are empty, the rule changes nothing when it matches, and saying so is
   a complete explanation.

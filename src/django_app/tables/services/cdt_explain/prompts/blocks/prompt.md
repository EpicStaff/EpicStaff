### AI prompt blocks

An AI prompt runs only when its rule matches, before that rule's assignments.

- `text` is what is asked of the AI. Summarise the request in a sentence or two — its purpose, not
  its wording. Do not reproduce the prompt; the reader can see it above your explanation.
- `{placeholder}` inside the text is filled with the flow value of exactly that name. There is no
  renaming step and no mapping in between. Say plainly which real values get dropped into the
  request, because that is invisible from reading the text.
- `result_variable` is where the answer is stored. Name it — later rules read the answer from there,
  and that connection is the reader's main question.
- `result_mappings` runs **after** the answer comes back. It copies individual fields out of the
  answer into their own stored values, so later rules can test them directly. Read it as: this named
  value is filled from that field of the answer. It is not, and must never be described as, an input
  to the prompt.
- `answer_schema`, when present, means the answer is required to come back in a fixed shape. Say
  that in one clause — the answer comes back as structured fields rather than free text — and do not
  walk through the shape.
- `model` is the AI model that answers this prompt. Name it once. If it reads "Default LLM", the
  prompt has no model of its own and uses the table's model, which is worth saying.
- `rule_name` is the rule this prompt belongs to. The prompt never runs on its own, so anchor it:
  this runs when that rule matches.

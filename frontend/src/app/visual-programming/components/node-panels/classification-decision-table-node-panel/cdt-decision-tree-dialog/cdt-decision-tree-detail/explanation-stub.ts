/**
 * Placeholder explanation text and model name. **Delete when the explanation
 * endpoints land** — none of them exists yet; the work is designed in
 * `.claude/notes/visual-programming/est-3467-handoff.md` and has not started.
 *
 * **Not a shape contract — swapping this import will not be enough.** This is one
 * string shown identically for every block. The real thing is keyed per block and
 * has states nothing here models (loading, failed, never generated, stale), so the
 * window will need an `explanation` input and the template those branches.
 *
 * Long on purpose: the section scrolls and collapses, and neither is verifiable
 * against two sentences.
 */

export const EXPLANATION_STUB_TEXT = [
    'This code prepares the execution context before the decision table runs. It validates and ' +
        'normalizes the incoming index value, records the current input data (index, row2, row3, and ' +
        'result), calculates the current loop pass, determines whether the loop condition (index < 2) ' +
        'will continue to pass, collects any input warnings, and stores this information together with ' +
        'timestamps and metadata in the context variable for use later in the workflow.',

    'The step runs before any rule is evaluated, so every value it writes is visible to all of the ' +
        'conditions below it. Anything it raises aborts the table before the first condition is ' +
        'reached, which is why the error branch leaves the rule region as a whole rather than any ' +
        'single rule.',

    'Input variables are resolved as arguments to this step rather than as a separate lookup. The ' +
        'map is read once, immediately before the code is invoked, and the resulting names are bound ' +
        'into the local scope the code executes in. A name that is absent from the incoming payload ' +
        'is bound as None rather than left undefined, so a missing field surfaces as a comparison ' +
        'against None instead of a NameError.',

    'Values written to the context variable survive for the remainder of the table. They are visible ' +
        'to every condition expression, to every prompt rendered from a matched rule, and to the ' +
        'set-variables step attached to that rule. They are not, however, written back to the graph ' +
        'unless the post-computation step returns them explicitly.',

    'Because this step runs on entry and the post-computation step runs on exit, the pair is the only ' +
        'place where state crosses the boundary of the table. A rule that needs to accumulate ' +
        'something across passes has to route it through the context variable here, since the rules ' +
        'themselves are evaluated against a fresh scope on every pass.',

    'Warnings collected during validation are not fatal. They are appended to the context and left ' +
        'for a downstream node to interpret, which keeps a partially malformed payload from ending ' +
        'the flow when the rules below it can still reach a sensible decision.',
].join('\n\n');

/** Which model produced the text above. Comes from the backend once it exists. */
export const EXPLANATION_STUB_MODEL = 'gpt-4o';

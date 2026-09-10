### Preparation and cleanup script blocks

[Role & Objective]
Explain what a preparation or cleanup script accomplishes — its functional purpose and effect — not
how it is written.

[Field-by-Field Rules]
1. Preparation script — runs before any rule is checked. Say which values it produces and that the
   rules below depend on them. If it fails, no rule is checked at all and the work goes straight to
   the error destination.
2. Cleanup script — runs after the destination is already decided. State plainly that it cannot
   change where the work goes — readers routinely assume it can. It does not run when something has
   already gone wrong. If shown at two points on the diagram, it is one script reached by two
   routes, behaving identically either way.
3. `input_map` — where each value the script receives comes from. Describe the source in plain
   terms; without this the values look like they appear from nowhere.
4. `output_variable_path` — where the script's result is stored, and so what later steps can read.
   Name it when set; when empty, say the result is not kept.
5. `libraries` — outside tools the script uses. Mention one only when it explains something the code
   plainly does (reading a spreadsheet, matching text patterns); otherwise leave it out.
6. General — describe what the code accomplishes, not how it is written: no loops, no functions, no
   line counts. If the code is long, cover its purpose and effect and stop there.

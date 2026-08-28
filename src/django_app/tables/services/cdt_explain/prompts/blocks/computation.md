### Preparation and cleanup script blocks

Both run a short script. What separates them is when, and what it is worth saying about each.

- A **preparation** script runs before any rule is checked. Its job is to make values ready for the
  rules to test, so tie it to that: say which values it produces, and that the rules below depend on
  them. If it fails, no rule is checked at all and the work goes straight to the error destination.
- A **cleanup** script runs after the destination is already decided. Say plainly that it cannot
  change where the work goes — readers routinely assume it can. It does not run when something has
  already gone wrong.
- `input_map` says where each value the script receives comes from. Describe the source in plain
  terms; without this the values look like they appear from nowhere.
- `output_variable_path` is where the script's result is stored, and therefore what later steps can
  read. Name it when it is set. When it is empty, the script's result is not kept.
- `libraries` are outside tools the script uses. Mention one only when it explains something the
  code plainly does — reading a spreadsheet, matching text patterns — otherwise leave it out.
- Describe what the code accomplishes, not how it is written. No loops, no functions, no line
  counts. If the code is long, cover its purpose and its effect and stop there.
- The same cleanup script is shown at two points on the diagram because the work can reach it by two
  routes. It is one script, and it behaves identically either way.

# EpicChat Widget — Test Prompts

Prompts to test each EpicChat response feature individually.

---

## 1. Rich Markdown Message

```
Reply with a message that demonstrates all markdown features: a heading, bold text, italic text, a fenced code block, a bullet list, a numbered list, and a hyperlink.
```

## 2. Editable Table with Multi-Select

```
Show a sortable, editable table of 5 team members with columns: name, role, department, score (number), active (boolean). Use multiSelect row selection, sort by score by default, and pre-select rows 0 and 2.
```

## 3. Read-Only Table

```
Show a read-only table (not editable) of 4 projects with columns: project name, status, deadline, budget. Sort by deadline.
```

## 4. Table with Column Groups (Unions)

```
Show a table with 6 columns grouped under two headers: "Personal Info" (name, age, city) and "Performance" (score, rating, projects). Include 4 rows of sample data.
```

## 5. Action Buttons — sendAction

```
Reply with a short message and two sendAction buttons: "Approve" and "Reject".
```

## 6. Link Button

```
Reply with a message and a link button that opens https://github.com.
```

## 7. Prompt Suggestion Chips

```
Reply with a greeting and three prompt suggestion chips: "Show all flows", "List agents", "Check status".
```

## 8. Process Tables Button

```
Show an editable table of 4 items with name and quantity columns, using multiSelect. Below it add a "Submit selections" button that sends the table data back (processTables action).
```

## 9. Build Mode Request

```
I want you to create a new Python file. Plan what you'll do and ask me for build permission.
```

## 10. Switch Agent Button

```
Reply with a message and a button that switches the conversation to flow 42.
```

## 11. Open Flow Navigation

```
Reply with a message and a button that navigates to flow 29 in the visual editor.
```

## 12. Open Node Navigation

```
Reply with a message and a button that opens a specific node in flow 29. Use a sample node ID.
```

## 13. Refresh Cache

```
Pretend you just modified flow 29. Explain that a page refresh is needed and offer a refresh button.
```

## 14. Post-Modification Flow (Build + Refresh + Navigate)

```
I want you to create a new start node in flow 29. Plan what you'll do, ask for build permission, and after building, offer both a refresh button and a button to open the flow.
```

## 15. Everything Combined

```
Show me ALL response features in one reply: a rich markdown message, an editable multiSelect table, a read-only table, a sendAction button, a link button, a processTables button, two prompt suggestion chips, an openFlow button, and a refreshCache button.
```

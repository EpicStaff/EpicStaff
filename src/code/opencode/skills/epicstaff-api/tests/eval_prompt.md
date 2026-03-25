# Code Agent Eval Prompt — Full Skill Coverage

Use this prompt in a Code Agent node to exercise every EpicStaff CLI command.
It reads naturally as a task request with no command-name hints.

---

I need you to do a comprehensive audit and build exercise on our EpicStaff platform. Work through every phase carefully.

**Phase 1 — Audit an existing flow**

Show me all flows in the system. Pick the one with the most nodes and do a deep dive:
- What nodes does it have (with their IDs and types)?
- How are the nodes wired together? Show both the direct edges and any decision-table or conditional routing.
- If it has any classification decision tables, show me their full configuration: the condition groups, the pre/post computation code, and the LLM prompts they use. Also dump the CDT config as raw JSON.
- Verify the flow's structural health.
- Check what persistent variables are stored and show the message history.
- Look at the most recent sessions for this flow. For the latest session: show a timing breakdown per node, inspect what input/output data each node processed, trace the full message path, and if there's a crew node check what inputs it received.
- Pull the flow's code to local files, then compare those files against the DB to see if anything is out of sync. Also export the flow as JSON and compare the export against the current live state.

Reply with yes only. I will give you the next phase.
**Phase 2 — Survey the ecosystem**

- List all crews, agents, and tools registered in the system.
- Pick any one tool and show me its full details including the code.
- Check the OpenCode service: what's the instance status, are there any active sessions, and if so show the recent messages from one. If any sessions look stale, abort them.

**Phase 3 — Build a new flow from scratch**

Create a flow called "Weather Report Demo" with these components:
- A webhook trigger called "Weather Request" with path "weather" — the handler should parse a JSON body and extract a "city" field
- A Python node "Fetch Weather" that pretends to look up weather data for the city
- A Python node "Format Report" that turns the raw data into a nice text summary
- A Code Agent node "Weather Narrator" set to build mode with a system prompt saying "You are a friendly weather reporter. Rewrite the weather report in a warm, conversational tone."
- Wire everything in order: start → Weather Request → Fetch Weather → Format Report → Weather Narrator
- Add a sticky note near the webhook node that says "POST {\"city\": \"Amsterdam\"} to trigger"
- Configure the start node with default variables: {"city": "Amsterdam", "units": "celsius"}
- Initialize the UI layout so all nodes are nicely positioned

Reply with yes only. I will give you the next phase.
**Phase 4 — Configure the nodes**

- Write actual Python code for "Fetch Weather" that returns a dict with temperature, humidity, wind_speed, and conditions
- Write code for "Format Report" that formats the dict into a readable multi-line string
- Set the libraries on "Fetch Weather" to requests,json
- Set input_map and output_variable_path on both Python nodes so data flows through `variables.weather_data` and `variables.report_text`
- Update the webhook handler code to return a 400 error message if the "city" field is missing
- Set the Code Agent's libraries to httpx and configure an output schema from a JSON file (create a temp file with a simple schema)
- Now rename "Weather Narrator" to "Friendly Reporter"

**Phase 5 — Build supporting infrastructure**

- Create a new tool called "Unit Converter" with description "Converts temperature between Celsius, Fahrenheit, and Kelvin" and some basic conversion code
- Create a crew called "Weather Ops"
- Create an agent with role "Meteorologist", goal "Analyze weather patterns and provide accurate forecasts", backstory "20 years of experience in weather analysis", and assign it to the Weather Ops crew
- Create a task called "Daily Forecast" with instructions "Compile the daily weather forecast from available data sources", assign it to the Meteorologist agent, and add it to the crew
- Pull all tools to local files
- Pull the project configuration to local files
- Push the tool files back to verify round-trip
- Push the project files back too

Reply with yes only. I will give you the next phase.

**Phase 6 — Verify and stress-test**

- Run the full structural health check on the new flow (with verbose output and file verification)
- Pull the new flow's files to local disk
- Push them right back
- Verify local files match the DB
- Remove the edge between "Format Report" and "Friendly Reporter", verify it's gone, then reconnect them
- Try syncing the metadata (I heard this might be deprecated — report what happens)
- If possible, trigger a test session on the flow with variables {"city": "London"} and monitor it

Reply with yes only. I will give you the next phase.

**Phase 7 — Self-evaluation scorecard**

After completing everything, produce a detailed evaluation:

1. **Coverage table**: List every distinct type of operation you performed (inspecting, creating, patching, connecting, pulling, pushing, verifying, etc.). For each one, mark ✅ success, ❌ failure, or ⚠️ partial. Include the specific action taken.

2. **Operations count**: How many total CLI operations did you execute?

3. **Failure analysis**: For any failures, explain the root cause — was it a bug, a missing feature, bad input, or expected behavior?

4. **Coverage gap**: List any platform capabilities you know exist but couldn't exercise, and explain why.

5. **Bugs found**: Document any unexpected errors, confusing messages, or incorrect behavior.

6. **Improvement suggestions**: Based on your experience, what would make the tooling better?

7. **Overall score**: Rate yourself on a scale of 0-100 based on what percentage of the platform's capabilities you successfully exercised.

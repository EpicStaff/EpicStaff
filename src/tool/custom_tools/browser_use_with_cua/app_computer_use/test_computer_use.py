from app_computer_use.computers import Computer
from app_computer_use.utils import create_response, check_blocklisted_url
from app_computer_use.computers import computers_config
from openai import OpenAI
from dotenv import load_dotenv
import os
import json
import re


load_dotenv()

client = OpenAI()

COMPUTER_ENV = os.getenv("COMPUTER_ENV", "docker")
if COMPUTER_ENV not in computers_config:
    raise ValueError(
        f"Unknown COMPUTER_ENV='{COMPUTER_ENV}'. Known: {list(computers_config.keys())}"
    )
ComputerClass = computers_config[COMPUTER_ENV]

TASK_PROMPT = """
You are testing a web application called **EpicFlow**.

Follow the test case below step by step, simulating a real user's behavior: clicking, scrolling, typing, navigating with the keyboard, etc.
Do not explain your thought process or describe your reasoning.  
Just perform the actions and briefly describe what happened on screen after each step.  
At the end of your response, clearly state either `PASSED` or `FAILED` on a separate line.  
If something fails, describe briefly what happened or what was on screen.  
Do not include any `Reasoning:` or detailed internal logic.  
Do not ask for confirmation or permission.

**Steps:**

1. Open the following URL:  
   http://epic-ai-tokarev.ddns.hysdev.com:8889/#!/login  
   - Use the browser’s address bar to enter the full URL and press Enter.  


2. Log in using these credentials:  
   - Username: `Cas P`  
   - Password: `Epica23!`
   Follow this procedure for logging in:  
   1) Click into the **Username** input field, type the username `Cas P`, then press **Tab**.  
   2) Click into the **Password** input field, type the password `Epica23!`, then press **Tab** to dismiss any warning messages.  
   3) Finally, click the login button to submit.

3. In the left sidebar menu (the vertical menu on the left side of the screen), locate the icon showing two people (a silhouette of two human figures).
    This icon is positioned approximately in the middle of the sidebar.
    Hover your mouse over the icon. A tooltip labeled "Resource management" should appear.
    In some cases, the label "Resource management" may be shown directly below the icon instead of as a tooltip.
    Once you confirm the label says "Resource management", click directly on the icon (not the label).
    After clicking, ensure that a table with users and groups is visible on the screen.
    If the table is not visible, it means the wrong tab was opened — go back to the sidebar and try clicking the correct icon again.

4. In the **first (left) column**, on the **first row**, locate the word **"Groups"**.  
   - To the right of the word "Groups," click the **blue plus icon**.  
   - A window titled **"Create New"** will appear.  
   - In this window, click on **"Multigroup"**.  
   - Enter the name `test` for the multigroup.  
   - Press **Enter** to confirm and create the multigroup.

5. In the **first (left) column**, on the **first row**, locate the word **"Groups"**.  
   - To the right of the word "Groups," click the **blue plus icon**.  
   - A window titled **"Create New"** will appear.  
   - In this window, click on **"Group"**.  
   - Enter the name `example` for the group.  
   - Press **Enter** to confirm and create the group.

6. Click on the multigroup name `test` to open its details window or panel.  
   - In the opened group details window, scroll down until you see the "Subgroups" section.  
   - To the right of the word "Subgroups", click the **green plus icon**.  
   - A popup window will appear with a list of available groups.  
   - Find the group named `example` and check the box next to it to add it as a subgroup.  
   - To finish adding, click the left mouse button anywhere outside the popup window to close it.  
   - Note: After this step, the position of the multigroup `test` in the table may change.  
     Be attentive and locate it again by its name if its position has changed.

7. Click on the multigroup name test again to reopen its details window.
    Important: After the previous step (adding a subgroup), the position of the multigroup test in the table may have changed.
    Do not click on any other group — make sure you are clicking on the correct multigroup whose name is exactly test.
    This will open a popup details window directly below the test multigroup row in the table.
    Inside this specific popup window, scroll down until you see the Subgroups section.
    Locate the subgroup named example.
    To the right of example, you will see a gray upward arrow icon.
    This icon is positioned above the Delete icon.
    Hover over the gray upward arrow icon.
    If the tooltip or icon label says "Exclude", click it to remove the subgroup.

8. Click on the multigroup name `test` once again to reopen its details window.  
   - **Note:** After the previous step, the **position of the multigroup `test` in the table may have changed**.  
     Be attentive and make sure you click on the correct **multigroup name** labeled exactly `test`.  
   - This will open a **popup details window directly below the `test` multigroup row** in the table.  
   - Inside this specific popup window, **scroll down** to the **Subgroups** section.  
   - Verify that the group named `example` is **no longer listed** among the subgroups.  
   - If the `example` group is still present, it means the removal **failed**.  
   - If it is not present, the removal was **successful**.
"""

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_state.json")


def load_task_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_task_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def mark_step_status(step_number: int, status: str):
    state = load_task_state()
    state[str(step_number)] = status
    save_task_state(state)


def split_prompt_and_steps(full_prompt: str):
    parts = full_prompt.split("**Steps:**", 1)
    if len(parts) != 2:
        raise ValueError("Prompt doesn't contain '**Steps:**'")

    test_description = parts[0].strip()
    raw = parts[1].replace("\r\n", "\n")

    step_re = re.compile(
        r"(?m)^\s*(?=(" r"\d+\.\s|" r"Step\s+\d+\s*[\u2014\u2013-]" r"))"
    )

    starts = [m.start() for m in step_re.finditer(raw)]
    if not starts:
        return test_description, [raw.strip()]

    starts.append(len(raw))
    steps = [raw[starts[i] : starts[i + 1]].strip() for i in range(len(starts) - 1)]
    return test_description, [s for s in steps if s]


def step_successful(text: str):
    return "PASSED" in text.upper()


def acknowledge_safety_check_callback(message: str) -> bool:
    print(f"Auto-acknowledge safety check: {message}")
    return True


def handle_item(item, computer: Computer):
    if item["type"] == "message":
        print(item["content"][0]["text"])

    if item["type"] == "computer_call":
        action = item["action"]
        action_type = action["type"]
        action_args = {k: v for k, v in action.items() if k != "type"}
        print(f"{action_type}({action_args})")

        getattr(computer, action_type)(**action_args)

        screenshot_base64 = computer.screenshot()
        pending_checks = item.get("pending_safety_checks", [])

        for check in pending_checks:
            if not acknowledge_safety_check_callback(check["message"]):
                raise ValueError(f"Safety check failed: {check['message']}")

        call_output = {
            "type": "computer_call_output",
            "call_id": item["call_id"],
            "acknowledged_safety_checks": pending_checks,
            "output": {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{screenshot_base64}",
            },
        }

        if computer.get_environment() == "browser":
            current_url = computer.get_current_url()
            call_output["output"]["current_url"] = current_url
            check_blocklisted_url(current_url)

        return [call_output]

    return []


def build_items_for_step(
    step_number: int, step_prompt: str, test_description: str, computer: Computer
):
    current_image = computer.screenshot()
    content = []

    state = load_task_state()
    # current_step_result = state.get(str(step_number))
    # if current_step_result:
    #     content.append({
    #         "type": "input_text",
    #         "text": (
    #             f"Note: This test step has already been executed before.\n"
    #             f"Here is what happened previously on this same step:\n{current_step_result['details']}\n"
    #             "Now you will try it again."
    #         )
    #     })

    previous_step_result = state.get(str(step_number - 1))
    if previous_step_result and previous_step_result["status"] == "PASSED":
        content.append(
            {
                "type": "input_text",
                "text": (
                    f"Here is what happened on the previous step:\n"
                    f"{previous_step_result['details']}"
                ),
            }
        )

    if test_description:
        instruction = (
            f"{test_description}\n\n"
            f"Test step {step_number}:\n\n"
            f"{step_prompt}\n\n"
            "After completing this step:\n"
            "- Briefly describe what actions were performed and what was visible on the screen.\n"
            "- End your answer with either PASSED or FAILED on a separate line.\n"
            "- Do not include any reasoning or internal thoughts."
        )
    else:
        instruction = (
            f"Test step {step_number}:\n\n"
            f"{step_prompt}\n\n"
            "After completing this step:\n"
            "- Briefly describe what actions were performed and what was visible on the screen.\n"
            "- End your answer with either PASSED or FAILED on a separate line.\n"
            "- Do not include any reasoning or internal thoughts."
        )

    content.append({"type": "input_text", "text": instruction})

    content.append(
        {"type": "input_image", "image_url": f"data:image/png;base64,{current_image}"}
    )

    return [{"role": "user", "content": content}]


def main(prompt):

    save_task_state({})
    state = {}

    import os

    orchestrator_mode = os.getenv("ORCHESTRATOR_COMPUTER_PROMPT") == "1"
    if orchestrator_mode:
        test_description = ""
        steps = [prompt]
    else:
        test_description, steps = split_prompt_and_steps(prompt)
    state = load_task_state()
    with ComputerClass() as computer:

        dimensions = computer.get_dimensions()
        tools = [
            {
                "type": "computer-preview",
                "display_width": dimensions[0],
                "display_height": dimensions[1],
                "environment": computer.get_environment(),
            }
        ]
        for idx, step in enumerate(steps, start=1):
            print(f"\n=== Executing Step {idx} ===\n")
            print(step)
            items = build_items_for_step(
                step_number=idx,
                step_prompt=step,
                test_description=test_description if idx == 1 else None,
                computer=computer,
            )

            print("\n--- TEXT INPUT TO MODEL ---")
            for item in items:
                if item["role"] == "user":
                    for block in item["content"]:
                        if block["type"] == "input_text":
                            print(block["text"])
            print("--- END TEXT INPUT ---\n")
            while True:
                response = create_response(
                    model="computer-use-preview",
                    input=items,
                    tools=tools,
                    truncation="auto",
                )

                if "output" not in response:
                    print(response)
                    raise ValueError("No output from model")

                items += response["output"]

                for item in response["output"]:
                    items += handle_item(item, computer)

                if items[-1].get("role") == "assistant":
                    final_text = items[-1]["content"][0]["text"]
                    print("Step result:\n", final_text)
                    step_result = {
                        "status": "PASSED" if step_successful(final_text) else "FAILED",
                        "details": final_text.strip(),
                    }
                    state[str(idx)] = step_result
                    save_task_state(state)
                    break
    return state


if __name__ == "__main__":
    main(TASK_PROMPT)

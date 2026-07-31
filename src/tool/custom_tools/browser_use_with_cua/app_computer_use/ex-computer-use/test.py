from playwright.sync_api import sync_playwright
from openai import OpenAI
import time
import base64

client = OpenAI()


def handle_model_action(page, action):
    """
    Given a computer action (e.g., click, double_click, scroll, etc.),
    execute the corresponding operation on the Playwright page.
    """
    action_type = action.type

    try:
        match action_type:

            case "click":
                x, y = action.x, action.y
                button = action.button
                print(f"Action: click at ({x}, {y}) with button '{button}'")
                # Not handling things like middle click, etc.
                if button != "left" and button != "right":
                    button = "left"
                page.mouse.click(x, y, button=button)

            case "scroll":
                x, y = action.x, action.y
                scroll_x, scroll_y = action.scroll_x, action.scroll_y
                print(
                    f"Action: scroll at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})"
                )
                page.mouse.move(x, y)
                page.evaluate(f"window.scrollBy({scroll_x}, {scroll_y})")

            case "keypress":
                keys = action.keys
                for k in keys:
                    print(f"Action: keypress '{k}'")
                    # A simple mapping for common keys; expand as needed.
                    if k.lower() == "enter":
                        page.keyboard.press("Enter")
                    elif k.lower() == "space":
                        page.keyboard.press(" ")
                    else:
                        page.keyboard.press(k)

            case "type":
                text = action.text
                print(f"Action: type text: {text}")
                page.keyboard.type(text)

            case "wait":
                print("Action: wait")
                time.sleep(2)

            case "screenshot":
                # Nothing to do as screenshot is taken at each turn
                print("Action: screenshot")

            case "drag":
                from_x, from_y = action.from_x, action.from_y
                to_x, to_y = action.to_x, action.to_y
                button = action.button if hasattr(action, "button") else "left"
                print(
                    f"Action: drag from ({from_x}, {from_y}) to ({to_x}, {to_y}) with button '{button}'"
                )

                if button not in ["left", "right"]:
                    button = "left"

                page.mouse.move(from_x, from_y)
                page.mouse.down(button=button)
                page.mouse.move(to_x, to_y)
                page.mouse.up(button=button)
            # Handle other actions here

            case _:
                print(f"Unrecognized action: {action}")

    except Exception as e:
        print(f"Error handling action {action}: {e}")


def get_screenshot(page):
    """
    Take a full-page screenshot using Playwright and return the image bytes.
    """
    return page.screenshot()


def computer_use_loop(instance, response):
    """
    Run the loop that executes computer actions until no 'computer_call' is found.
    """
    while True:
        computer_calls = [
            item for item in response.output if item.type == "computer_call"
        ]
        if not computer_calls:
            print("No computer call found. Output from model:")
            for item in response.output:
                print(item)
            break  # Exit when no computer calls are issued.

        # We expect at most one computer call per response.
        computer_call = computer_calls[0]
        last_call_id = computer_call.call_id
        action = computer_call.action

        # Execute the action (function defined in step 3)
        handle_model_action(instance, action)
        time.sleep(1)  # Allow time for changes to take effect.

        # Take a screenshot after the action (function defined in step 4)
        screenshot_bytes = get_screenshot(instance)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        # Send the screenshot back as a computer_call_output
        response = client.responses.create(
            model="computer-use-preview",
            previous_response_id=response.id,
            tools=[
                {
                    "type": "computer_use_preview",
                    "display_width": 1920,
                    "display_height": 1080,
                    "environment": "browser",
                }
            ],
            input=[
                {
                    "call_id": last_call_id,
                    "type": "computer_call_output",
                    "output": {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{screenshot_base64}",
                    },
                }
            ],
            truncation="auto",
        )

    return response


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        chromium_sandbox=True,
        args=["--disable-extensions", "--disable-popup-blocking", "--no-sandbox"],
    )
    page = browser.new_page()
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto("http://epic-ai-tokarev.ddns.hysdev.com:8800/")
    # page.wait_for_timeout(6000)
    page.wait_for_load_state("load")

    screenshot_bytes = get_screenshot(page)
    screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    response = client.responses.create(
        model="computer-use-preview",
        tools=[
            {
                "type": "computer_use_preview",
                "display_width": 1920,
                "display_height": 1080,
                "environment": "browser",
            }
        ],
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": """You are testing a web application (EpicFlow). 
                            Please follow the test case below step by step and check whether it passes or fails.
                            For each step, act as a human user would: click, scroll, type, etc.
                            After executing the steps, evaluate if the expected result was achieved and respond with PASSED or FAILED and explain why.\n\n

                            Test Case: Remove group from multigroup\n\n
                            Steps:\n
                            2. Log in to EpicFlow using:\n
                               - Username: Cas P\n
                               - Password: Epica23!\n
                            3. On the left side, find the Resource Management tab and navigate to it.\n"
                            4. Click on the plus icon next to the word 'Groups' at the top left, and create a new multigroup with name test, save it\n
                            5. Click on the plus icon next to the word 'Groups' at the top left, and create a new group with name example, save it\n
                            6. Click on the group with name test and scroll down\n
                            7. Click on the plus icon next to the word Subgroups and add example to subgroup\n
                            8. Click on the multigroup’s name test\n"
                              . Click the 'Exclude' button\n"
                              - Expectation: A green notification message is shown, and the group card is closed\n
                            10. Click on the multigroup’s name again\n"
                               - Expectation: The removed group is no longer present in the group card\n\n
                            At the end, report whether the test passed or failed, and provide a reason if it failed.""",
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{screenshot_base64}",
                    },
                ],
            }
        ],
        reasoning={"summary": "concise"},
        truncation="auto",
    )

    computer_use_loop(page, response)

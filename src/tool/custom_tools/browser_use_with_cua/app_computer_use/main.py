from agent.agent import Agent
from computers import LocalPlaywrightBrowser


def main(user_input=None):
    with LocalPlaywrightBrowser() as computer:
        agent = Agent(computer=computer)
        items = []
        while True:
            user_input = input("> ")
            items.append({"role": "user", "content": user_input})
            output_items = agent.run_full_turn(items, debug=True, show_images=True)
            items += output_items


if __name__ == "__main__":
    main()

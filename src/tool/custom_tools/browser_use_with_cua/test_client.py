import os
import asyncio
import json
from fastmcp import Client


def serialize_response(resp) -> str:
    try:
        return json.dumps(resp.model_dump(), ensure_ascii=False, indent=2)
    except AttributeError:
        pass
    try:
        return json.dumps(resp.dict(), ensure_ascii=False, indent=2)
    except AttributeError:
        pass
    try:
        return json.dumps(resp, ensure_ascii=False, indent=2)
    except TypeError:
        return str(resp)


async def main():
    url = os.getenv("FASTMCP_URL", "http://127.0.0.1:8080/mcp")

    use_existing = input("Use existing session? (y/n): ").strip().lower() == "y"
    session_id = input("Enter session_id: ").strip() if use_existing else None

    prompt = input("Enter MAIN TASK: ").strip()

    async with Client(url) as client:
        try:
            result = await client.call_tool(
                "run_browser_use",
                {
                    "prompt": prompt,
                    "session_id": session_id,
                },
            )
            print("Response:")
            print(serialize_response(result))
            session_id = (
                result.structured_content.get("session_id")
                if hasattr(result, "structured_content")
                else session_id
            )
        except Exception as e:
            print(f"Error: {e}")
            return

        task_counter = 1
        while True:
            next_prompt = input(
                f"\n[{task_counter}] Enter NEXT TASK (or type 'exit'): "
            ).strip()
            if next_prompt.lower() in ("exit", "quit"):
                print("Exiting interactive session.")
                try:
                    print("Restarting browser-use session...")
                    restart_resp = await client.call_tool("restart_browser_use", {})
                    print("Restart result:")
                    print(serialize_response(restart_resp))
                except Exception as restart_error:
                    print(f"Error during restart: {restart_error}")

                restart = (
                    input("Do you want to start a NEW session? (y/n): ").strip().lower()
                )
                if restart == "y":
                    return await main()
                else:
                    print("Exiting completely.")
                break

            if not next_prompt:
                print("Empty prompt. Try again.")
                continue

            try:
                result = await client.call_tool(
                    "run_browser_use",
                    {
                        "prompt": prompt,
                        "next_prompt": next_prompt,
                        "session_id": session_id,
                    },
                )
                print("Response:")
                print(serialize_response(result))
                task_counter += 1
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())

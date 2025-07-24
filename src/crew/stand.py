import gc
import traceback
import psutil
import os
from crewai import Crew, Task, LLM, Agent
from crewai.tools import tool


@tool
def example_tool():
    """
    An example tool that can be used in a Crew task.
    """
    return "This is an example tool response."


def generate_crew(n=10):
    for i in range(n):  # Fix: iterate with range
        llm = LLM(model="gpt-4o-mini", temperature=0.7, api_key="your_api_key_here")
        tools = [example_tool]
        test_agent = Agent(
            name="Test Agent",
            description="An agent that uses the example tool.",
            role="assistant",
            goal="Assist with tasks using the example tool.",
            backstory="An agent designed to demonstrate tool usage.",
            tools=tools,
            llm=llm,
            cache=False,
        )
        tasks = [
            Task(
                name="Stand",
                description="A task that uses the example tool.",
                tools=tools,
                expected_output="This is an example tool response.",
                agent=test_agent,
            )
        ]
        yield Crew(
            name=f"Example Crew {i}",
            llm=llm,
            tasks=tasks,
            agents=[test_agent],
            cache=False,
        )


def memory_usage():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024**2  # in MB


def main():
    print(f"[BEFORE] Memory usage: {memory_usage():.2f} MB")

    crew_list = []
    counter = 0
    for crew in generate_crew(1000):
        crew_list.append(crew)
        counter += 1
        try:
            crew.kickoff()
            print(f"[CREW {counter}] Kickoff successful: {crew.name}")
        except Exception as e:
            if counter % 1000 == 0:
                print(f"[ERROR] Kickoff failed for crew {counter}: {str(e)}")
                print(traceback.format_exc())  # Proper traceback
    
    print(f"[BEFORE CLEANUP] Memory usage: {memory_usage():.2f} MB")
    crew = None
    crew_list.clear()  # Clear the list to free memory
    del crew_list
    gc.collect()  # Force garbage collection

    print(f"[AFTER CLEANUP] Memory usage: {memory_usage():.2f} MB")


if __name__ == "__main__":
    main()

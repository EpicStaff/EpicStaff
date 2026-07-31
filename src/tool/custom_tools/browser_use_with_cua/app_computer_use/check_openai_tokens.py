import os
import sys
from dotenv import load_dotenv
from openai import OpenAI

print("Script started")

loaded = load_dotenv()
print(f"dotenv loaded: {loaded}")

print("cwd:", os.getcwd())

api_key = os.getenv("OPENAI_API_KEY")
print("OPENAI_API_KEY from env:", "FOUND" if api_key else "MISSING")

if not api_key:
    sys.exit("OPENAI_API_KEY not found. Please check your .env file.")

client = OpenAI(api_key=api_key)

try:
    models = client.models.list()
    print(f"/models OK. Found {len(models.data)} models.")
except Exception as e:
    print("Error calling /models:", e)

try:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say hello"}],
        max_tokens=5,
    )
    print("Completion:", resp.choices[0].message.content)
except Exception as e:
    print("Completion error:", e)

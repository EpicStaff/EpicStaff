import os
import requests
from dotenv import load_dotenv

load_dotenv()
url = "https://api.deepseek.com/v1/chat/completions"
headers = {"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}"}
payload = {
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "ping"}],
    "temperature": 0,
}
r = requests.post(url, json=payload, headers=headers, timeout=30)
print(r.status_code, r.text)

import asyncio
import aiohttp
import time

URL = "http://127.0.0.1:8000/api/run-session/"
HEADERS = {
    "accept": "application/json",
    "Content-Type": "application/json",
    "X-CSRFTOKEN": "AKc0556QdwcJdhvz5jPMYGVqgCjfs3vZk2PfleC5dyx8YUkivEnffrdiZGE9MyhU",
}
PAYLOAD = {"graph_id": 15}

CONCURRENCY = 1  # Number of simultaneous requests
TOTAL_REQUESTS = 25  # Total requests to send


async def send_request(session, idx):
    try:
        async with session.post(URL, headers=HEADERS, json=PAYLOAD) as response:
            status = response.status
            data = await response.text()
            print(f"[{idx}] Status: {status}")
            await asyncio.sleep(1)
    except Exception as e:
        print(f"[{idx}] Error: {e}")


async def stress_test():
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for i in range(TOTAL_REQUESTS):
            tasks.append(send_request(session, i + 1))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    start_time = time.time()
    asyncio.run(stress_test())
    print(f"Finished in {time.time() - start_time:.2f} seconds")

from locust import HttpUser, TaskSet, task, between

class UserBehavior(TaskSet):
    @task
    def run_session(self):
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "X-CSRFTOKEN": "AKc0556QdwcJdhvz5jPMYGVqgCjfs3vZk2PfleC5dyx8YUkivEnffrdiZGE9MyhU",
        }
        payload = {"graph_id": 15}
        with self.client.post("/api/run-session/", json=payload, headers=headers, catch_response=True) as response:
            if response.status_code != 201:
                response.failure(f"Status code: {response.status_code}")
            else:
                response.success()

class WebsiteUser(HttpUser):
    tasks = [UserBehavior]
    wait_time = between(1, 1)  # аналогично await asyncio.sleep(1)
    host = "http://127.0.0.1:8000"
# 🚀 Webhook User Guide

This guide explains how to use Webhook Triggers to start your graphs from external applications or services.

## What is a Webhook Trigger?

A Webhook Trigger provides a unique, public URL for one of your graphs. When any external application (like Stripe, GitHub, or a custom script) sends data (via an `HTTP POST` request) to this URL, it instantly triggers your graph to run.

The `WebhookTriggerNode` is a special node you add to your graph. It serves two purposes:
1.  **It's the Link:** The node's unique ID is used in the public URL to identify which graph to run.
2.  **It's the Processor:** It acts as the starting point of your graph and runs Python code to process, validate, or transform the incoming data before passing it to the rest of your workflow.

## How to Set Up Your Webhook

The process involves two main steps:
1.  **In the Graph Editor:** Add and configure the `WebhookTriggerNode`.
2.  **In Your External Service:** Get the public URL and send data to it.

---

### Step 1: Add and Configure the WebhookTriggerNode

1.  Open the graph you want to trigger.
2.  From the node menu, find and drag a **`WebhookTriggerNode`** onto your canvas.
3.  **This node must be set as the entrypoint for your graph.**
4.  Select the node to configure its built-in Python code.
5.  Connect the `WebhookTriggerNode` to the next node in your workflow (e.g., an `LLMNode` or a `PythonNode`).

#### Understanding the Node's Python Code

The Python code inside the `WebhookTriggerNode` is designed to process the data sent to your webhook.

* **Receiving Data:** The JSON data from your `POST` request is automatically passed into your code in a variable named `inputs`. For example, if an external service sends `{"customer_name": "Jane", "amount": 100}`, your code can access `inputs["customer_name"]`.

* **Returning Data:** Your code **must** return a Python dictionary. This dictionary will become the new set of graph variables for all subsequent nodes.

**Example Code:**

Imagine you receive the following JSON payload:
`{"user": "alex", "event_type": "new_order", "item_id": "prod_123"}`

Your `WebhookTriggerNode`'s Python code could be:

```python
# The 'inputs' variable holds the JSON payload
user_name = inputs.get("user", "guest")
event = inputs.get("event_type", "unknown")

# You can process the data
processed_message = f"Processing {event} for user {user_name}."

# The returned dictionary REPLACES the graph variables
return {
    "message_for_llm": processed_message,
    "product_code": inputs.get("item_id"),
    "original_payload": inputs
}
```


### Step 2: Get Your Public Webhook URL
The webhook service generates a unique public URL for you. You need to combine this Base URL with your Trigger ID.

Find your Base URL: The public-facing URL for the webhook service is logged to the console when the service starts. It will look something like this:

🌐 Tunnel endpoint is: [https://your-unique-subdomain.ngrok-free.dev/webhooks/](https://your-unique-subdomain.ngrok-free.dev/webhooks/)<custom_id>/
Your Base URL is https://your-unique-subdomain.ngrok-free.dev.

Find your Trigger ID: This is the ID of the WebhookTriggerNode you created in Step 1. You can find this by checking the node's details in the graph editor or via the API.

Combine them: Your final, public webhook URL will be:[Base URL]/webhooks/[Trigger ID]/

### Example:

Base URL: https://your-unique-subdomain.ngrok-free.dev

Trigger ID: 1

Final URL: https://your-unique-subdomain.ngrok-free.dev/webhooks/1/

### Step 3: Send Data to the URL
You can now configure your external service to send an HTTP POST request with a JSON body to your final URL.

You can use a simple curl command from your terminal to test it:

#### Replace with your actual URL and desired JSON data
curl -X POST "[https://your-unique-subdomain.ngrok-free.dev/webhooks/1/](https://your-unique-subdomain.ngrok-free.dev/webhooks/1/)" \
-H "Content-Type: application/json" \
-d "{\"event\": \"test\", \"user\": \"test_user\"}"

If successful, this will immediately start your graph, and the `WebhookTriggerNode` will execute its Python code on the `{"event": "test", "user": "test_user"}` data.

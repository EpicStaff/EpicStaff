# EpicChat Agent Persistence — Backend API

## Problem

When the user clicks **Connect chat** on a flow, the widget creates an agent in `sessionStorage`. On page reload or container restart, the agent is lost because `unique-user-id` is not set, so storage falls back to `sessionStorage` instead of `localStorage`.

## Solution: Backend-Driven Agent List

Instead of relying on browser storage, the backend now persists which flows are connected to EpicChat. The widget should fetch connected flows from the API at startup and create agents from the response.

## What's Already Implemented (Backend + Frontend)

### 1. Graph Model — `epicchat_enabled` field

```
Graph.epicchat_enabled  (BooleanField, default=False)
```

When the user clicks **Connect chat**, the frontend PATCHes `epicchat_enabled: true` on the graph **and** sends `agent.create` to the widget (existing behavior).

### 2. API Endpoints

**Get all connected flows (lightweight):**
```
GET /api/graph-light/?epicchat_enabled=true
```

Response:
```json
{
  "results": [
    {
      "id": 42,
      "name": "My Flow",
      "description": "Handles customer inquiries",
      "tags": [],
      "epicchat_enabled": true
    }
  ]
}
```

**Toggle connection on a single graph:**
```
PATCH /api/graphs/{id}/
Content-Type: application/json

{"epicchat_enabled": true}
```

### 3. Full graph endpoint also includes the field
```
GET /api/graphs/{id}/
```
Returns `epicchat_enabled` in the response body.

## What the Widget Needs to Do

### On Startup (`ngOnInit` or equivalent)

1. Fetch connected flows:
   ```
   GET /api/graph-light/?epicchat_enabled=true
   ```

2. For each flow in the response, create/update an agent:
   ```ts
   for (const flow of response.results) {
     agentService.createOrUpdateAgent({
       name: flow.name,
       description: flow.description,
       flowId: flow.id,
       flowUrl: baseApiUrl,
     });
   }
   ```

3. Remove any agents whose `flowId` is no longer in the response (flow was disconnected).

### On `agent.create` Command (existing)

No change needed — the frontend already sends this command AND patches `epicchat_enabled`.

### Disconnect Flow (implemented)

When the widget emits `agent.disconnected` with `{ flowId }`, the frontend PATCHes `epicchat_enabled: false`. The widget removes the agent from its UI.

## API Base URL

The widget needs the API base URL to construct the fetch call. This should be passed as an attribute or derived from the existing `flowUrl` pattern on agents. Current format: `http://localhost:8000/api/`.

## Migration

Migration `0152_add_epicchat_enabled_to_graph` adds the field with `default=False`, so all existing flows start disconnected. No data migration needed.

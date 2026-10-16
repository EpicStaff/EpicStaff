# Realtime Provider Architecture

This document covers the multi-provider realtime AI system: its interface contract, how each provider is implemented, audio routing, tool calling, and how to add a new provider.

For Twilio-specific setup see [voice-twilio-integration.md](voice-twilio-integration.md).

---

## Table of Contents

1. [Overview](#overview)
2. [IRealtimeAgentClient interface](#irealtimeagentclient-interface)
3. [Provider Comparison](#provider-comparison)
4. [Audio Flow](#audio-flow)
5. [Tool Calling Flow](#tool-calling-flow)
6. [Factory: Adding a New Provider](#factory-adding-a-new-provider)
7. [Gemini-Specific: Session Reconnection](#gemini-specific-session-reconnection)
8. [Gemini-Specific: Tool Calling](#gemini-specific-tool-calling)
9. [Troubleshooting per Provider](#troubleshooting-per-provider)

---

## Overview

The realtime service bridges two WebSocket connections:

```
Browser / Twilio
      │  (audio + text events)
      ▼
ConversationService / VoiceCallService
      │
      ▼  factory.create(rt_provider="openai"|"elevenlabs"|"gemini")
IRealtimeAgentClient  ← single interface, three adapters
      │
      ▼
AI Provider WebSocket  (OpenAI / ElevenLabs / Gemini Live)
```

`VoiceCallService` and `ConversationService` contain **zero provider checks**. All format differences are encapsulated inside provider adapters.

---

## IRealtimeAgentClient interface

`domain/ports/i_realtime_agent_client.py`

Every provider adapter must implement:

| Method | When called | Notes |
|--------|-------------|-------|
| `connect()` | Before any other call | Opens WebSocket, performs handshake |
| `close()` | On session end or error | Must be idempotent |
| `handle_messages()` | Runs as `asyncio.Task` | Long-running receive loop |
| `process_message(msg)` | Browser → provider | Translates frontend events |
| `send_audio(ulaw8k_b64)` | Twilio audio chunk | Adapters convert from µ-law 8kHz |
| `send_conversation_item_to_server(text)` | LISTEN mode wake-word | Inject user text turn |
| `request_response(data)` | After sending text | No-op for auto-VAD providers |
| `on_stream_start()` | Twilio `start` event | OpenAI sends `response.create` |
| `call_tool(call_id, name, args)` | Tool call from provider | Execute + send result back |

Properties: `stream_sid` (set by Twilio bridge), `is_twilio` (flag for audio format).

---

## Provider Comparison

| Feature | OpenAI | ElevenLabs | Gemini |
|---------|--------|-----------|--------|
| Model | `gpt-4o-realtime-preview` | configurable LLM | `gemini-2.0-flash-live-001` |
| Input audio (Twilio) | g711_ulaw natively | µ-law → PCM 16k inside adapter | µ-law → PCM 16k inside adapter |
| Output audio (Twilio) | g711_ulaw natively | PCM 24k → µ-law 8k inside handler | PCM 24k → µ-law 8k inside handler |
| Turn detection | `server_vad` (explicit config) | Auto | Gemini auto-VAD |
| `request_response` | Sends `response.create` | No-op | No-op |
| `on_stream_start` | Sends `response.create` | No-op | No-op |
| Tool calling | ✅ Awaited inline | ✅ Awaited inline | ✅ Background task |
| Session reconnect | ❌ Not needed | ❌ Not needed | ✅ Auto-reconnect on server close |
| Session versioning | ❌ | ❌ | ✅ (`_session_version` counter) |
| Conversation history on reconnect | ❌ | ❌ | ✅ Injected via system instruction |
| Protocol | OpenAI Realtime API | ElevenLabs Conversational AI | Gemini Live API |

---

## Audio Flow

### Twilio → Provider (input)

```
Twilio MediaStream
  │  base64 g711-ulaw 8kHz chunks
  │  accumulated until ≥ 2000 bytes
  ▼
VoiceCallService._flush_audio()
  │
  ▼
client.send_audio(ulaw8k_b64)
  │
  ├─ OpenAI:    forwards as-is (g711_ulaw is native)
  ├─ ElevenLabs: audioop.ulaw2lin → ratecv 8k→16k → send as PCM
  └─ Gemini:    audioop.ulaw2lin → ratecv 8k→16k → send_realtime_input(PCM 16k)
```

### Provider → Twilio (output)

```
AI Provider audio output
  │
  ▼
ServerEventHandler.handle_event()  (per provider)
  │
  ├─ OpenAI:    response.audio.delta forwarded as-is (already g711_ulaw)
  ├─ ElevenLabs: PCM 24k → audioop.ratecv 24k→8k → audioop.lin2ulaw → base64
  └─ Gemini:    PCM 24k → audioop.ratecv 24k→8k → audioop.lin2ulaw → base64
  │
  ▼
on_server_event({"type": "response.audio.delta", "delta": <base64>})
  │
  ▼
VoiceCallService._send_audio_to_twilio()
```

The `is_twilio=True` flag tells each server event handler to convert output audio before dispatching.

---

## Tool Calling Flow

### OpenAI / ElevenLabs (inline / awaited)

```
Server event: function_call_arguments.done
  │
  ▼
ServerEventHandler.handle_event()
  │
  ▼  await client.call_tool(call_id, name, args)   ← blocks receive loop
ToolManagerService.execute()
  │  result
  ▼
provider.send_tool_response / send_tool_result
  │
  ▼
Receive loop resumes
```

### Gemini (background task)

```
Server event: tool_call
  │
  ▼
GeminiServerEventHandler._handle_tool_call()
  │
  ├─ asyncio.ensure_future(client.call_tool(...))   ← non-blocking
  │     │
  │     ▼  (runs concurrently)
  │   ToolManagerService.execute() via Redis
  │     │  result
  │     ▼
  │   session version check  ← if session replaced: drop response
  │     │
  │     ▼
  │   _session.send_tool_response()  (try/except: session may close)
  │     │
  │     ▼
  │   _conversation_history updated (survives reconnect)
  │
  └─ Receive loop continues immediately (not blocked)
```

Tool calling in Gemini is non-blocking because:
1. The receive loop must stay active to receive `session_resumption_update` keep-alives
2. Gemini sessions close quickly if the message count is exceeded — blocking for a tool result increases that risk
3. The session may close during tool execution; the session-version guard detects this

---

## Factory: Adding a New Provider

**File:** `infrastructure/providers/factory.py`

1. Implement `IRealtimeAgentClient` in `infrastructure/providers/<name>/`.

   Required files:
   ```
   infrastructure/providers/newprovider/
   ├── __init__.py
   ├── newprovider_realtime_agent_client.py   ← implements IRealtimeAgentClient
   └── event_handlers/
       ├── __init__.py
       ├── newprovider_client_event_handler.py
       └── newprovider_server_event_handler.py
   ```

2. Add a branch in `factory.py`:

   ```python
   if config.rt_provider == "newprovider":
       from infrastructure.providers.newprovider.newprovider_realtime_agent_client import (
           NewProviderRealtimeAgentClient,
       )

       client = NewProviderRealtimeAgentClient(
           api_key=config.rt_api_key,
           connection_key=config.connection_key,
           on_server_event=on_server_event,
           tool_manager_service=tool_manager_service,
           rt_tools=rt_tools,
           instructions=instructions,
       )
       client.is_twilio = is_twilio
       return client
   ```

3. Use lazy import (inside the `if` block) to avoid import errors when the provider's SDK is not installed.

4. Add tests in `tests/infrastructure/providers/test_newprovider_*.py`.

5. Add a factory test in `tests/infrastructure/test_factory.py`:
   ```python
   @patch("infrastructure.providers.newprovider.newprovider_realtime_agent_client.SomeSDK")
   def test_create_newprovider(mock_sdk, factory, ...):
       config = _make_config(rt_provider="newprovider")
       result = factory.create(config=config, ...)
       assert type(result).__name__ == "NewProviderRealtimeAgentClient"
   ```

### Checklist for a correct adapter

- [ ] `close()` is idempotent (second call is a no-op)
- [ ] `send_audio()` guards against `_session is None`
- [ ] `call_tool()` has try/except around the network send
- [ ] Server event handler converts output audio to µ-law 8kHz when `is_twilio=True`
- [ ] `handle_messages()` handles `asyncio.CancelledError` (task cancellation on call end)

---

## Gemini-Specific: Session Reconnection

### Why Gemini reconnects

Gemini Live API enforces a **server-side session limit** (number of messages or duration). When the limit is reached the server closes the WebSocket cleanly — the `receive()` generator ends without raising an exception.

This happens regularly during normal calls, typically every 25–60 messages. Without reconnection, the call would drop.

### Reconnection flow

```
receive() loop ends normally
  │
  ├─ WARNING: "receive() loop ended after N messages — server closed connection, reconnecting"
  │
  ▼
handle_messages() reconnect block:
  await self.close()
  self.server_event_handler.reset()
  await self.connect()
  self._session_version += 1
  INFO: "Gemini: reconnected successfully"
  │
  ▼
New receive() loop starts with fresh session
```

If `connect()` raises `asyncio.CancelledError` (call ended while reconnecting), the loop exits cleanly.

### Context preservation across sessions

`_conversation_history` accumulates all turns during the call:

| Event | What is saved |
|-------|--------------|
| `input_transcription` | `{"role": "user", "text": ...}` |
| `turn_complete` | `{"role": "model", "text": <transcript>}` |
| `call_tool` result | `{"role": "model", "text": "[Tool name(args) → result]"}` |

On reconnect, `_build_system_instruction()` appends the full history to the system prompt:

```
{original instructions}

---
Conversation so far (continue naturally from here):
User: ...
Assistant: ...
[Tool echo({"text": "hi"}) → hello]
```

### Race condition protection

When the call ends (Twilio WebSocket closes) while a reconnect is in progress:

```
handle_messages (task)          VoiceCallService.execute (main coro)
─────────────────────           ──────────────────────────────────
  await self.close()              iter_text() raises ConnectionClosedOK
  await self.connect()    ←──     except → finally: message_task.cancel()
  CancelledError caught               await message_task  ← waits for task exit
  break                               await rt_agent_client.close()  ← safe now
  await self.close()
```

`await message_task` in `voice_call_service.execute` is critical — without it, two `close()` calls race on `_session_cm.__aexit__()`.

`close()` is protected by `asyncio.Lock` so concurrent calls are serialized.

---

## Gemini-Specific: Tool Calling

### Session version guard

Every reconnect increments `_session_version`. When `call_tool()` starts executing it captures the current version:

```python
session_version = self._session_version

result = await tool_manager_service.execute(...)  # may take 1-2 seconds

if self._session_version != session_version:
    # Session was replaced while tool was running
    # The new session has no pending tool call — drop the response
    return
```

This prevents sending a tool response to a session that didn't request it (which would cause a Gemini protocol error).

### What happens when session closes mid-tool

```
msg #5: tool_call received
  │
  ├─ asyncio.ensure_future(call_tool("ls", {command: "ls"}))
  │     └─ tool starts executing concurrently
  │
  ├─ receive loop continues: msg #6, #7, ... #25
  │
  ▼
receive() loop ends (server closes session)
  │
  ▼  reconnect starts
close()  →  _session_version += 1  →  connect()
  │
  │  tool execution completes
  ▼
call_tool: session_version check fails → tool response dropped
  │         result saved to _conversation_history
  ▼
new session starts with history injected in system prompt
  │
  ▼
Gemini aware of tool result context — may re-issue tool call if needed
```

---

## Troubleshooting per Provider

### OpenAI

| Symptom | Cause |
|---------|-------|
| `websockets.exceptions.ConnectionClosedError` during call | Network issue or OpenAI session expired (max ~15 min) |
| No audio output on Twilio | `output_audio_format` not set to `g711_ulaw`; factory forces this when `is_twilio=True` |
| Tool calls not working | `arguments` field must be valid JSON; verify `response.function_call_arguments.done` event |

### ElevenLabs

| Symptom | Cause |
|---------|-------|
| "Agent not provisioned" error | `ElevenLabsAgentProvisioner` failed to create/fetch the agent; check API key and agent config |
| Distorted Twilio audio | PCM→µ-law conversion uses `audioop`; ensure audio chunks are 16-bit mono |
| Interruptions not clearing Twilio buffer | ElevenLabs emits `interruption` not `input_audio_buffer.speech_started`; both are handled in `VoiceCallService._handle_provider_event` |

### Gemini

| Symptom | Cause |
|---------|-------|
| `receive() loop ended after N messages` (WARNING, not ERROR) | Normal — server-side session limit. Reconnect is automatic. |
| `anext(): asynchronous generator is already running` | Two concurrent `close()` calls. `asyncio.Lock` in `close()` serializes them; warning is benign. |
| Tool response dropped (`session was replaced`) | Session closed during tool execution. Result is in history for next session. |
| `Gemini: invalid voice 'X', falling back to 'Puck'` | Voice name not in `_VALID_GEMINI_VOICES`. Valid: Puck, Charon, Kore, Fenrir, Aoede, Leda, Orus, Zephyr. |
| Model not found error on connect | Preview models (`gemini-3.1-flash-live-preview`) may not be available in all regions or may be deprecated. Use a stable model like `gemini-2.0-flash-live-001`. |
| Rapid interruptions drop the call | User interrupts while Gemini session limit is near. Each interruption generates audio chunks; session closes quickly. Reconnect handles this — check for `asyncio.CancelledError` in close() log. |

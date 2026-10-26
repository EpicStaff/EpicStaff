"""Lab only: the plugin node's real EgressPolicyWriter, driven over a Unix socket.

`serve` stands in for the agent: it calls `start()` (empty policy files), then keeps the writer,
and the passwords it issued, in memory and answers one command per connection:

  issue-password <identifier>   prints the password on stdout of `call` (the lab keeps it in a file)
  remove-password <identifier>
  write-hosts <json object>     identifier -> hosts, the whole policy

Each answer starts with `ok <epoch time of the write>`, so the lab can time when Squid applies it.
es_plugins is mounted read-only at /opt/es_plugins; the policy volume at /policy.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

SOCKET = "/run/lab-policy-writer.sock"


async def serve() -> None:
    from es_plugins.egress.policy_writer import EgressPolicyWriter

    writer = EgressPolicyWriter(Path("/policy"))
    await writer.start()

    async def handle(reader: asyncio.StreamReader, stream: asyncio.StreamWriter) -> None:
        command, _, argument = (await reader.readline()).decode().strip().partition(" ")
        if command == "issue-password":
            password = await writer.issue_password(argument)
            answer = f"ok {time.time():.3f} {password}"
        elif command == "remove-password":
            await writer.remove_password(argument)
            answer = f"ok {time.time():.3f}"
        elif command == "write-hosts":
            await writer.write_hosts(json.loads(argument))
            answer = f"ok {time.time():.3f}"
        else:
            answer = f"error unknown command {command}"
        stream.write(answer.encode() + b"\n")
        await stream.drain()
        stream.close()

    server = await asyncio.start_unix_server(handle, SOCKET)
    print("policy writer ready", flush=True)
    async with server:
        await server.serve_forever()


async def call(command: list[str]) -> None:
    reader, stream = await asyncio.open_unix_connection(SOCKET)
    stream.write(" ".join(command).encode() + b"\n")
    await stream.drain()
    print((await reader.readline()).decode().strip())
    stream.close()


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        asyncio.run(serve())
    else:
        asyncio.run(call(sys.argv[2:]))

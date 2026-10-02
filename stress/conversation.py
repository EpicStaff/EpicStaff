#!/usr/bin/env python3
"""Multi-turn chat load: N users each play the same conversation, one session per message.

Each turn sends the visitor message plus that user's chat history so far as `variables.context`,
waits for the session to end, reads `final_result.message` as the bot reply and appends both to the
history for the next turn. Users start at a fixed rate (open-loop arrivals); inside a conversation
the next message waits for the previous reply (closed loop, like a real visitor).

Same run directory and memory sampling as bench.py; fired.jsonl rows carry step_rate "turnN", so
`analyze.py` reports each turn separately. Standard library only. See stress/README.md.
"""

import argparse
import concurrent.futures
import itertools
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import bench

DONE_STATUSES = {"end", "error", "stop", "expired", "wait_for_user"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost")
    parser.add_argument("--graph-id", type=int, required=True)
    parser.add_argument("--users", type=int, required=True, help="number of chats, each plays every turn")
    parser.add_argument("--users-per-minute", type=float, required=True, help="how fast new chats start")
    parser.add_argument("--conversation", type=Path, default=bench.REPO_ROOT / "stress" / "chat" / "conversation.json")
    parser.add_argument("--think-seconds", type=float, default=0, help="pause between a bot reply and the next message")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--turn-timeout-minutes", type=float, default=10)
    parser.add_argument("--cooldown-minutes", type=float, default=5)
    bench.add_common_args(parser)
    args = parser.parse_args()
    if not 0 < args.users <= bench.MAX_WORKERS:
        parser.error(f"--users must be 1..{bench.MAX_WORKERS}")
    if args.users_per_minute <= 0:
        parser.error("--users-per-minute must be positive")
    args.turns = json.loads(args.conversation.read_text(encoding="utf-8"))["turns"]
    if not args.turns or not all(isinstance(turn, str) and turn.strip() for turn in args.turns):
        parser.error(f"{args.conversation}: `turns` must be a list of non-empty strings")
    args.variables = None
    bench.check_common_args(parser, args)
    return args


def get_session(args, session_id, detailed):
    url = f"{args.api.rstrip('/')}/api/sessions/{session_id}/" + ("" if detailed else "?detailed=false")
    request = urllib.request.Request(url, headers=bench.api_headers(args))
    with urllib.request.urlopen(request, timeout=bench.REQUEST_TIMEOUT_S) as response:
        return json.loads(response.read())


def wait_for_session(args, session_id, stop):
    """-> (status, final variables or None, error). Polls the light serializer; the full one once at the end."""
    deadline = time.monotonic() + args.turn_timeout_minutes * 60
    last_error = None
    while time.monotonic() < deadline:
        if stop.wait(args.poll_seconds):
            return None, None, "interrupted"
        try:
            status = get_session(args, session_id, detailed=False).get("status")
        except Exception as error:  # a slow/overloaded API is a data point, keep polling until the deadline
            last_error = f"poll {type(error).__name__}: {error}"
            continue
        if status in DONE_STATUSES:
            try:
                return status, get_session(args, session_id, detailed=True).get("variables") or {}, None
            except Exception as error:
                return status, None, f"read {type(error).__name__}: {error}"
    return None, None, last_error or "turn timeout"


def play_user(user_index, args, fired_log, turns_log, run_counter, run_tag, stop):
    chat_session_id = f"bench-{run_tag}-u{user_index}"
    history = []
    for turn_index, user_input in enumerate(args.turns, start=1):
        if stop.is_set():
            return
        variables = {"context": {"user_input": user_input, "chat_history": list(history),
                                 "chat_session_id": chat_session_id}}
        started = time.monotonic()
        record = bench.fire(next(run_counter), f"turn{turn_index}", args, fired_log, variables,
                            user=user_index, turn=turn_index)
        outcome = {"user": user_index, "turn": turn_index, "session_id": record["session_id"], "status": None,
                   "turn_s": None, "history_messages": len(history), "reply_chars": None, "error": record["error"]}
        reply = None
        if record["session_id"] is not None:
            status, final_variables, error = wait_for_session(args, record["session_id"], stop)
            reply = ((final_variables or {}).get("final_result") or {}).get("message")
            outcome.update(status=status, error=error, reply_chars=len(reply) if reply else None,
                           turn_s=round(time.monotonic() - started, 2))
        turns_log.write(outcome)
        if outcome["status"] != "end" or not reply:
            print(f"[user {user_index}] stopped at turn {turn_index}: {outcome['status'] or outcome['error']}")
            return  # without the reply the rest of this conversation would not be the scripted one
        history += [{"role": "user", "content": user_input}, {"role": "assistant", "content": reply}]
        if args.think_seconds and stop.wait(args.think_seconds):
            return


def run_conversations(args, executor, fired_log, futures, run_dir):
    turns_log = bench.FiredLog(run_dir / "turns.jsonl")
    run_counter = itertools.count(1)
    stop = threading.Event()
    interval_s = 60.0 / args.users_per_minute
    started = time.monotonic()
    print(f"[load] {args.users} users x {len(args.turns)} turns, {args.users_per_minute} new users/min")
    try:
        for user_index in range(1, args.users + 1):
            delay_s = started + (user_index - 1) * interval_s - time.monotonic()
            if delay_s > 0:
                time.sleep(delay_s)
            futures.append(executor.submit(play_user, user_index, args, fired_log, turns_log,
                                           run_counter, run_dir.name, stop))
        concurrent.futures.wait(futures)
    except KeyboardInterrupt:
        stop.set()  # users exit at their next poll; let them write their last turns.jsonl line first
        concurrent.futures.wait(futures, timeout=args.poll_seconds + 2 * bench.REQUEST_TIMEOUT_S)
        raise
    finally:
        for future in futures:
            if future.done() and future.exception():
                print(f"[load] user crashed: {future.exception()!r}")
        turns_log.close()


if __name__ == "__main__":
    bench.run_benchmark(parse_args(), run_conversations)

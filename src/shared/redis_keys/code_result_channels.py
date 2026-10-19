def crew_code_result_channel(code_result_channel: str) -> str:
    """Name of the pub/sub channel the sandbox publishes crew's code results to.

    Crew sets ``CodeTaskData.reply_to_crew_channel`` and reads only this channel,
    so it never parses results meant for django_app, agent or realtime, and they
    never parse crew's. Crew and sandbox both derive the name from their shared
    ``CODE_RESULT_CHANNEL`` setting; the sandbox never takes a channel name from
    the task payload.
    """
    return f"{code_result_channel}:crew"

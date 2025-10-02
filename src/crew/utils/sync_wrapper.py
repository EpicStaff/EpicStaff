import asyncio

def sync_wrapper(coro_func, *args, **kwargs):
    """Wrap an async function so it can be called synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import threading

        result_container = {}

        def thread_target():
            result_container["result"] = asyncio.run(coro_func(*args, **kwargs))

        t = threading.Thread(target=thread_target)
        t.start()
        t.join()
        return result_container.get("result")
    else:
        return asyncio.run(coro_func(*args, **kwargs))

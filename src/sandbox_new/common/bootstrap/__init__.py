"""Bootstrap helpers shared by both processes.

Only ``logging`` lives here. Each process has its own composition root --
``manager/bootstrap/runtime.py`` for the manager, ``worker/main.py`` for the worker --
so nothing in ``common`` assembles either side.
"""

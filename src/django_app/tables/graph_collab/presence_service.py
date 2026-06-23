from tables.graph_collab.protocol import EditorInfo


class GraphPresenceService:
    """
    Service that keeps all info about the active channels in specific graph.
    Adds and removes new users and channels to/from the graph.
    Prevents the deduplication when returning the list of active editors
    """

    def __init__(self):
        # graph_id -> {channel_name -> EditorInfo}
        self._store: dict[int, dict[str, EditorInfo]] = {}

    def add(self, graph_id: int, channel_name: str, editor: EditorInfo) -> None:
        if graph_id not in self._store:
            self._store[graph_id] = {}
        self._store[graph_id][channel_name] = editor

    def remove(self, graph_id: int, channel_name: str) -> None:
        graph_editors = self._store.get(graph_id)
        if not graph_editors:
            return
        graph_editors.pop(channel_name, None)
        if not graph_editors:
            del self._store[graph_id]

    def get_editors(self, graph_id: int) -> list[EditorInfo]:
        graph_editors = self._store.get(graph_id, {})
        seen_user_ids: set[int] = set()
        result: list[EditorInfo] = []
        for editor in graph_editors.values():
            if editor.user_id not in seen_user_ids:
                seen_user_ids.add(editor.user_id)
                result.append(editor)
        return result

    def count_editors(self, graph_id: int) -> int:
        """Return the number of active channels (connections) for *graph_id*."""
        return len(self._store.get(graph_id, {}))

    def has_editors(self, graph_id: int) -> bool:
        """Return True if at least one channel is connected for *graph_id*."""
        return self.count_editors(graph_id) > 0

    def active_graph_ids(self) -> list[int]:
        """Return a snapshot list of all graph ids with at least one active editor.

        Returns a list copy of the internal dict keys so that callers iterating
        with awaits in the loop do not observe concurrent add/remove mutations.
        """
        return list(self._store.keys())


presence_service = GraphPresenceService()

import { NodeType } from '@shared/models';

import {
    liveGraph,
    liveNote,
    livePython,
    liveStart,
    liveSubgraph,
    liveTask,
} from '../utils/testing/live-graph.fixture';
import { NodeAuthorshipStore } from './node-authorship.store';

const UNKNOWN = { created_by: null, created_at: null, last_edited_by: null, last_edited_at: null };
const grace = { id: 9, display_name: 'Grace Hopper', avatar_url: null };

const authorshipOfRow = (
    row: typeof livePython | typeof liveTask | typeof liveSubgraph | typeof liveStart | typeof liveNote
) => ({
    created_by: row.created_by,
    created_at: row.created_at,
    last_edited_by: row.last_edited_by,
    last_edited_at: row.last_edited_at,
});

describe('NodeAuthorshipStore', () => {
    it('reads only the four authorship fields of every switched-on node list, keyed by type and id', () => {
        const store = new NodeAuthorshipStore();

        store.replaceFromGraph(liveGraph);

        expect(store.authorshipOf({ type: NodeType.PYTHON, backendId: livePython.id })).toEqual(
            authorshipOfRow(livePython)
        );
        expect(store.authorshipOf({ type: NodeType.TASK, backendId: liveTask.id })).toEqual(authorshipOfRow(liveTask));
        // The same id under another type is another row.
        expect(store.authorshipOf({ type: NodeType.TASK, backendId: livePython.id })).toEqual(UNKNOWN);
        expect(store.authorshipOf({ type: NodeType.SUBGRAPH, backendId: liveSubgraph.id })).toEqual(
            authorshipOfRow(liveSubgraph)
        );
    });

    it('holds the Start and Note rows too, for the footer of their own windows', () => {
        const store = new NodeAuthorshipStore();

        store.replaceFromGraph(liveGraph);

        expect(store.authorshipOf({ type: NodeType.START, backendId: liveStart.id })).toEqual(
            authorshipOfRow(liveStart)
        );
        expect(store.authorshipOf({ type: NodeType.NOTE, backendId: liveNote.id })).toEqual(authorshipOfRow(liveNote));
        expect(store.authorshipOf({ type: NodeType.NOTE, backendId: liveStart.id })).toEqual(UNKNOWN);
    });

    it('knows no author for a node that is not saved yet', () => {
        const store = new NodeAuthorshipStore();
        store.replaceFromGraph(liveGraph);

        expect(store.authorshipOf({ type: NodeType.PYTHON, backendId: null })).toEqual(UNKNOWN);
    });

    it('replaces everything on each graph: fresh rows win, rows the graph no longer lists are dropped', () => {
        const store = new NodeAuthorshipStore();
        store.replaceFromGraph(liveGraph);

        store.replaceFromGraph({
            ...liveGraph,
            task_node_list: [],
            python_node_list: [{ ...livePython, last_edited_by: grace, last_edited_at: '2026-10-06T10:00:00Z' }],
        });

        expect(store.authorshipOf({ type: NodeType.PYTHON, backendId: livePython.id })).toEqual(
            expect.objectContaining({ last_edited_by: grace, last_edited_at: '2026-10-06T10:00:00Z' })
        );
        expect(store.authorshipOf({ type: NodeType.TASK, backendId: liveTask.id })).toEqual(UNKNOWN);
    });
});

import { NodeType } from '@shared/models';

import { liveGraph, livePython } from '../utils/testing/live-graph.fixture';
import { VersionPreviewNodeAuthorshipStore } from './version-preview-node-authorship.store';

const UNKNOWN = { created_by: null, created_at: null, last_edited_by: null, last_edited_at: null };
const grace = { id: 9, display_name: 'Grace Hopper', avatar_url: null };
const recorded = { created_by: grace, created_at: '2026-03-12T13:28:23Z', last_edited_by: null, last_edited_at: null };

describe('VersionPreviewNodeAuthorshipStore', () => {
    it('finds a node detached from the backend by its canvas id', () => {
        const store = new VersionPreviewNodeAuthorshipStore();

        store.replaceFromVersion(new Map([['python-canvas-id', recorded]]));

        expect(store.authorshipOf({ id: 'python-canvas-id', type: NodeType.PYTHON, backendId: null })).toEqual(
            recorded
        );
        expect(store.authorshipOf({ id: 'other-canvas-id', type: NodeType.PYTHON, backendId: null })).toEqual(UNKNOWN);
        // Without a canvas id there is nothing to find it by.
        expect(store.authorshipOf({ type: NodeType.PYTHON, backendId: null })).toEqual(UNKNOWN);
    });

    it('replaces everything on each version', () => {
        const store = new VersionPreviewNodeAuthorshipStore();
        store.replaceFromVersion(new Map([['python-canvas-id', recorded]]));

        store.replaceFromVersion(new Map());

        expect(store.authorshipOf({ id: 'python-canvas-id', type: NodeType.PYTHON, backendId: null })).toEqual(UNKNOWN);
    });

    it('does not look nodes up by type and backend id, even after a graph was loaded into it', () => {
        const store = new VersionPreviewNodeAuthorshipStore();
        store.replaceFromGraph(liveGraph);

        expect(store.authorshipOf({ id: 'python-canvas-id', type: NodeType.PYTHON, backendId: livePython.id })).toEqual(
            UNKNOWN
        );
    });
});

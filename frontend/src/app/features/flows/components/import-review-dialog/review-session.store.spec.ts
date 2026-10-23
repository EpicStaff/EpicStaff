import { TestBed } from '@angular/core/testing';

import { FlowNodeReviewItem, ReviewPythonCode } from '../../../../core/models/review-item.model';
import { ReviewSessionStore } from './review-session.store';

function code(source: string): ReviewPythonCode {
    return { code: source, entrypoint: 'main', libraries: '', global_kwargs: {} };
}

function pythonReviewItem(nodeId: number | null, source: string): FlowNodeReviewItem {
    return {
        kind: 'flow_node',
        flow_name: 'Orders',
        node_id: nodeId,
        node_name: 'Fetch',
        node_type: 'PythonNode',
        python_code: code(source),
    };
}

describe('ReviewSessionStore', () => {
    let store: ReviewSessionStore;

    beforeEach(() => {
        TestBed.configureTestingModule({ providers: [ReviewSessionStore] });
        store = TestBed.inject(ReviewSessionStore);
    });

    it('keeps two same-named nodes of one flow apart, each with its own code and review state', () => {
        store.init([pythonReviewItem(1, 'def main(): return 1'), pythonReviewItem(2, 'def main(): return 2')], {
            Orders: [
                { id: 1, name: 'Fetch', node_type: 'PythonNode' },
                { id: 2, name: 'Fetch', node_type: 'PythonNode' },
                // Ids are unique per node type only: this table shares the first node's id and has no code.
                { id: 1, name: 'Fetch', node_type: 'ClassificationDecisionTableNode' },
            ],
        });

        const [first, second, table] = store.flowNodes('Orders');
        expect(new Set([first.key, second.key, table.key]).size).toBe(3);
        expect(first.codes.map((field) => field.code)).toEqual(['def main(): return 1']);
        expect(second.codes.map((field) => field.code)).toEqual(['def main(): return 2']);
        expect(table.codeFieldCount).toBe(0);
        // Opening the review marks the first entry reviewed; the namesake still waits for review.
        expect(store.isNodeReviewed(first)).toBe(true);
        expect(store.isNodeReviewed(second)).toBe(false);
        expect(store.flowReviewRemaining('Orders')).toBe(1);
    });

    it.each([
        { file: 'no id', fileNodeId: null },
        { file: 'a string id the backend sent as null', fileNodeId: '7' },
    ])('matches a node by name when the file has $file', ({ fileNodeId }) => {
        store.init([pythonReviewItem(null, 'def main(): return 1')], {
            Orders: [{ id: fileNodeId as number | null, name: 'Fetch', node_type: 'PythonNode' }],
        });

        const nodes = store.flowNodes('Orders');
        expect(nodes).toHaveLength(1);
        expect(nodes[0].codes.map((field) => field.code)).toEqual(['def main(): return 1']);
    });

    it('still lists reviewed code that matches no node of the file', () => {
        store.init([pythonReviewItem(9, 'def main(): return 9')], {
            Orders: [{ id: 1, name: 'Fetch', node_type: 'PythonNode' }],
        });

        const nodes = store.flowNodes('Orders');
        expect(nodes.map((node) => [node.name, node.codeFieldCount])).toEqual([
            ['Fetch', 0],
            ['Fetch', 1],
        ]);
        expect(store.reviewableEntries.map((entry) => (entry.kind === 'code' ? entry.code : null))).toEqual([
            code('def main(): return 9'),
        ]);
    });
});

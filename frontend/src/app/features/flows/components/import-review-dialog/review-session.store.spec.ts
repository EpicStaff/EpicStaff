import { TestBed } from '@angular/core/testing';

import {
    FlowNodeReviewItem,
    McpToolReviewItem,
    PythonCodeToolReviewItem,
    ReviewExpression,
    ReviewPythonCode,
} from '../../../../core/models/review-item.model';
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

function pythonTool(name: string, source: string): PythonCodeToolReviewItem {
    return {
        kind: 'python_code_tool',
        name,
        description: null,
        python_code: code(source),
        variables: [],
        use_storage: false,
    };
}

function mcpTool(name: string, transport: string): McpToolReviewItem {
    return { kind: 'mcp_tool', name, transport };
}

function decisionTableItem(
    expressions: ReviewExpression[],
    extra: Partial<FlowNodeReviewItem> = {}
): FlowNodeReviewItem {
    return {
        kind: 'flow_node',
        flow_name: 'Orders',
        node_id: 3,
        node_name: 'Route',
        node_type: 'DecisionTableNode',
        expressions,
        ...extra,
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

    describe('nodes the backend reads as the same node', () => {
        const fetchNode = { id: null, name: 'Fetch', node_type: 'PythonNode' };

        it.each([
            { case: 'two id-less namesakes, absent from the file list', items: [null, null], fileNodes: [] },
            {
                case: 'two id-less namesakes, both in the file list',
                items: [null, null],
                fileNodes: [fetchNode, fetchNode],
            },
            { case: 'one id-less namesake in the file list', items: [null, null], fileNodes: [fetchNode] },
            {
                case: 'the same id twice',
                items: [4, 4],
                fileNodes: [{ id: 4, name: 'Fetch', node_type: 'PythonNode' }],
            },
        ])('keeps the code of each node reviewable on its own: $case', ({ items, fileNodes }) => {
            store.init([pythonReviewItem(items[0], 'return 1'), pythonReviewItem(items[1], 'return 2')], {
                Orders: fileNodes,
            });

            expect(store.reviewableEntries.map((entry) => (entry.kind === 'code' ? entry.code.code : null))).toEqual([
                'return 1',
                'return 2',
            ]);
            // Opening the review reviews the first entry only.
            expect(store.isReviewComplete()).toBe(false);
            expect(store.flowReviewRemaining('Orders')).toBe(1);

            store.goToNextReviewEntry();
            store.goToNextReviewEntry();
            expect(store.isReviewComplete()).toBe(true);
        });
    });

    describe('tools', () => {
        it('gives same-named tools their own entries, each opened and reviewed through its own row', () => {
            store.init([pythonTool('t', 'return 1'), pythonTool('t', 'return 2')], {});

            store.goToToolCode('PythonCodeTool', 1);
            expect(currentCode()).toBe('return 2');
            store.goToToolCode('PythonCodeTool', 0);
            expect(currentCode()).toBe('return 1');

            // Opening the review marks the first tool reviewed; its namesake still blocks the import.
            expect(store.isToolReviewed('PythonCodeTool', 0)).toBe(true);
            expect(store.isToolReviewed('PythonCodeTool', 1)).toBe(false);
            expect(store.isReviewComplete()).toBe(false);

            store.toggleToolReviewed('PythonCodeTool', 1);
            expect(store.isReviewComplete()).toBe(true);
        });

        it('resolves a row to the tool at its position among the tools of its own entity type', () => {
            store.init([mcpTool('Search', 'https://mcp.example'), pythonTool('Search', 'return 1')], {});

            expect([store.hasPythonCode('PythonCodeTool', 0), store.isMcpTool('PythonCodeTool', 0)]).toEqual([
                true,
                false,
            ]);
            expect([store.hasPythonCode('MCPTool', 0), store.isMcpTool('MCPTool', 0)]).toEqual([false, true]);
            expect([store.hasPythonCode('Flow', 0), store.isMcpTool('Flow', 0)]).toEqual([false, false]);
            expect(store.hasPythonCode('PythonCodeTool', 1)).toBe(false);

            store.goToToolCode('MCPTool', 0);
            const entry = store.currentReviewEntry();
            expect(entry?.kind === 'mcp' ? entry.transport : null).toBe('https://mcp.example');
        });

        it('opens the first MCP tool when nothing needs review', () => {
            store.init([mcpTool('Search', 'stdio')], {});

            expect(store.currentReviewEntry()).toMatchObject({ kind: 'mcp', name: 'Search', transport: 'stdio' });
        });
    });

    describe('decision-table expressions', () => {
        const expressions: ReviewExpression[] = [
            { label: 'Is VIP', code: 'customer["vip"]' },
            { label: 'Set discount', code: 'discount = 10' },
        ];

        it('makes the expressions one code entry that blocks the import until reviewed', () => {
            // A tool first: opening the review marks the first entry reviewed.
            store.init([pythonTool('t', 'return 1'), decisionTableItem(expressions)], {
                Orders: [{ id: 3, name: 'Route', node_type: 'DecisionTableNode' }],
            });

            const [node] = store.flowNodes('Orders');
            expect(node.fieldLabels).toEqual(['Expressions']);
            expect(node.codes.map((field) => field.code)).toEqual([
                '# Is VIP\ncustomer["vip"]\n\n# Set discount\ndiscount = 10',
            ]);
            expect(store.isReviewComplete()).toBe(false);

            store.toggleNodeReviewed(node);
            expect(store.isReviewComplete()).toBe(true);
        });

        it('adds the expressions after the pre-computation code', () => {
            store.init([decisionTableItem(expressions, { pre_python_code: code('def main(): pass') })], {});

            const [node] = store.flowNodes('Orders');
            expect(node.fieldLabels).toEqual(['Pre-computation', 'Expressions']);
            expect(store.reviewableEntries).toHaveLength(2);
        });

        it('keeps a multi-line label on its comment line', () => {
            store.init([decisionTableItem([{ label: 'Is VIP\nimport os\r\n  now', code: 'True' }])], {});

            expect(store.flowNodes('Orders')[0].codes[0].code).toBe('# Is VIP import os now\nTrue');
        });
    });

    function currentCode(): string | null {
        const entry = store.currentReviewEntry();
        return entry?.kind === 'code' ? entry.code.code : null;
    }
});

import { NodeType } from '@shared/models';

import { hasNodeDetails, NODE_TYPES_WITH_DETAILS } from './node-details.util';

const TYPES_WITH_DETAILS = [
    NodeType.PYTHON,
    NodeType.END,
    NodeType.AGENT,
    NodeType.TASK,
    NodeType.KNOWLEDGE_RETRIEVER,
    NodeType.FILE_EXTRACTOR,
    NodeType.KEY_VALUE,
    NodeType.AUDIO_TO_TEXT,
    NodeType.TABLE,
    NodeType.CLASSIFICATION_TABLE,
    NodeType.WEBHOOK_TRIGGER,
    NodeType.TELEGRAM_TRIGGER,
    NodeType.SCHEDULE_TRIGGER,
    NodeType.SUBGRAPH,
    // No side panel: their own window shows the authorship in a footer.
    NodeType.START,
    NodeType.NOTE,
];

describe('node details opt-in', () => {
    it('switches on exactly the sixteen node types the product asked for', () => {
        expect([...NODE_TYPES_WITH_DETAILS].sort()).toEqual([...TYPES_WITH_DETAILS].sort());
        for (const type of TYPES_WITH_DETAILS) {
            expect(hasNodeDetails(type)).toBe(true);
        }
    });

    it('leaves LLM and conditional-edge nodes off (and tool, which has no graph node list)', () => {
        const typesWithout = Object.values(NodeType).filter((type) => !hasNodeDetails(type));

        expect(typesWithout.sort()).toEqual([NodeType.EDGE, NodeType.LLM, NodeType.TOOL].sort());
    });
});

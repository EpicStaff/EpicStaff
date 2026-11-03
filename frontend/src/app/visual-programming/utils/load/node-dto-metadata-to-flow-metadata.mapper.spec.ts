import { NodeType } from '@shared/models';

import { hasOutdatedStoredSize } from './node-dto-metadata-to-flow-metadata.mapper';

describe('hasOutdatedStoredSize', () => {
    const DRAWN = { width: 330, height: 60 };

    it.each([
        ['a size the node is no longer drawn at', NodeType.AGENT, true, { size: { width: 900, height: 40 } }],
        ['only the height differing', NodeType.TASK, true, { size: { width: 330, height: 40 } }],
        ['only the width differing', NodeType.PYTHON, true, { size: { width: 340, height: 60 } }],
        ['the size the node is drawn at', NodeType.AGENT, false, { size: { width: 330, height: 60 } }],
        ['only a position', NodeType.AGENT, false, { position: { x: 1, y: 2 } }],
        ['a null size', NodeType.AGENT, false, { size: null }],
        ['no metadata', NodeType.AGENT, false, undefined],
        ['null metadata', NodeType.AGENT, false, null],
        ['a note size other than the drawn one', NodeType.NOTE, false, { size: { width: 420, height: 260 } }],
    ])('%s (%s row) is outdated: %s', (_label, nodeType, expected, metadata) => {
        expect(hasOutdatedStoredSize(metadata, nodeType, DRAWN)).toBe(expected);
    });
});

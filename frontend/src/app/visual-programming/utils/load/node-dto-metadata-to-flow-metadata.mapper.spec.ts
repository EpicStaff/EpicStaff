import { NodeType } from '@shared/models';

import {
    hasOutdatedStoredSize,
    mapNodeDtoMetadataToFlowNodeMetadata,
} from './node-dto-metadata-to-flow-metadata.mapper';

function mapPosition(x: unknown, y: unknown) {
    return mapNodeDtoMetadataToFlowNodeMetadata({ position: { x, y } }, NodeType.PYTHON).position;
}

function mapSize(width: unknown, height: unknown, nodeType = NodeType.PYTHON) {
    return mapNodeDtoMetadataToFlowNodeMetadata({ size: { width, height } }, nodeType).size;
}

describe('mapNodeDtoMetadataToFlowNodeMetadata', () => {
    it('passes a normal position through unchanged', () => {
        const result = mapNodeDtoMetadataToFlowNodeMetadata({ position: { x: -120.5, y: 340 } }, NodeType.PYTHON);

        expect(result.position).toEqual({ x: -120.5, y: 340 });
    });

    it('replaces only the invalid coordinate of a position', () => {
        expect(mapPosition(5, Infinity)).toEqual({ x: 5, y: 0 });
    });

    it.each([
        ['null metadata', null],
        ['undefined metadata', undefined],
        ['empty metadata', {}],
        ['null position and size', { position: null, size: null }],
    ])('falls back to defaults for %s', (_label, metadata) => {
        const result = mapNodeDtoMetadataToFlowNodeMetadata(metadata, NodeType.PYTHON);

        expect(result.position).toEqual({ x: 0, y: 0 });
        expect(result.size).toEqual({ width: 330, height: 60 });
    });

    it.each([
        ['Infinity', Infinity],
        ['-Infinity', -Infinity],
        ['NaN', NaN],
        ['a numeric string', '100'],
        ['null', null],
        ['an object', {}],
    ])('replaces a non-finite or non-number position (%s) with 0', (_label, value) => {
        expect(mapPosition(value, value)).toEqual({ x: 0, y: 0 });
    });

    it.each([
        ['1e20', 1e20, 1_000_000],
        ['-1e20', -1e20, -1_000_000],
        ['just above the limit', 1_000_001, 1_000_000],
        ['exactly the limit', 1_000_000, 1_000_000],
    ])('clamps a huge position (%s)', (_label, value, expected) => {
        expect(mapPosition(value, value)).toEqual({ x: expected, y: expected });
    });

    it.each([
        ['a normal size', 400],
        ['a huge size', 1e20],
        ['zero', 0],
        ['NaN', NaN],
        ['a string', '500'],
    ])('ignores the stored size of a node other than a note (%s)', (_label, value) => {
        expect(mapSize(value, value)).toEqual({ width: 330, height: 60 });
    });

    it.each([
        ['a normal size', 420, 420],
        ['exactly the maximum', 10_000, 10_000],
        ['just above the maximum', 10_001, 10_000],
        ['1e20', 1e20, 10_000],
        ['below the minimum', 0.5, 1],
    ])('keeps a note size within bounds (%s)', (_label, value, expected) => {
        expect(mapSize(value, value, NodeType.NOTE)).toEqual({ width: expected, height: expected });
    });

    it.each([
        ['zero', 0],
        ['negative', -50],
        ['Infinity', Infinity],
        ['NaN', NaN],
        ['a string', '500'],
        ['null', null],
    ])('opens a note with an invalid stored size (%s) at the default size', (_label, value) => {
        expect(mapSize(value, value, NodeType.NOTE)).toEqual({ width: 200, height: 150 });
    });
});

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

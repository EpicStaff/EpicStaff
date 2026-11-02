import { NodeType } from '@shared/models';

import { mapNodeDtoMetadataToFlowNodeMetadata } from './node-dto-metadata-to-flow-metadata.mapper';

function mapPosition(x: unknown, y: unknown) {
    return mapNodeDtoMetadataToFlowNodeMetadata({ position: { x, y } }, NodeType.PYTHON).position;
}

function mapSize(width: unknown, height: unknown) {
    return mapNodeDtoMetadataToFlowNodeMetadata({ size: { width, height } }, NodeType.PYTHON).size;
}

describe('mapNodeDtoMetadataToFlowNodeMetadata', () => {
    it('passes a normal position and size through unchanged', () => {
        const result = mapNodeDtoMetadataToFlowNodeMetadata(
            { position: { x: -120.5, y: 340 }, size: { width: 400, height: 90 } },
            NodeType.PYTHON
        );

        expect(result.position).toEqual({ x: -120.5, y: 340 });
        expect(result.size).toEqual({ width: 400, height: 90 });
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
        ['Infinity', Infinity],
        ['NaN', NaN],
        ['a string', '500'],
        ['null', null],
    ])('replaces an invalid size (%s) with the default', (_label, value) => {
        expect(mapSize(value, value)).toEqual({ width: 330, height: 60 });
    });

    it.each([
        ['zero', 0, 1],
        ['negative', -50, 1],
        ['exactly the minimum', 1, 1],
        ['exactly the maximum', 10_000, 10_000],
        ['just above the maximum', 10_001, 10_000],
        ['1e20', 1e20, 10_000],
    ])('clamps size (%s)', (_label, value, expected) => {
        expect(mapSize(value, value)).toEqual({ width: expected, height: expected });
    });
});

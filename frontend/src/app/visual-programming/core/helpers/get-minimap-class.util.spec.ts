import { NodeType } from '@shared/models';

import { NodeModel } from '../models/node.model';
import { getMinimapClassForNode } from './get-minimap-class.util';

function makeNode(type: NodeType): NodeModel {
    return {
        id: 'n1',
        backendId: null,
        nodeUuid: null,
        type,
        node_name: 'test',
        color: '#000',
        icon: 'icon',
        ports: null,
        position: { x: 0, y: 0 },
        size: { width: 100, height: 60 },
        input_map: {},
        output_variable_path: null,
        data: {} as never,
    } as NodeModel;
}

describe('getMinimapClassForNode', () => {
    it('returns the node-type prefix as a kebab-case CSS class', () => {
        const result = getMinimapClassForNode(makeNode(NodeType.AGENT));
        expect(result).toEqual(['Agent-Node']);
    });

    it('replaces spaces with hyphens for multi-word prefixes', () => {
        const result = getMinimapClassForNode(makeNode(NodeType.CLASSIFICATION_TABLE));
        expect(result).toEqual(['Classification-Decision-Table']);
    });

    it('returns an empty array when type is falsy', () => {
        const node = makeNode(NodeType.AGENT);
        (node as unknown as { type: string }).type = '';
        expect(getMinimapClassForNode(node)).toEqual([]);
    });
});

import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { matchNodes } from './match-nodes';

function node(id: string, type: NodeType, nodeUuid: string | null): NodeModel {
    return { id, type, nodeUuid } as NodeModel;
}

describe('matchNodes', () => {
    it('matches by uuid, never by canvas id', () => {
        const matching = matchNodes(
            [node('same-id', NodeType.PYTHON, 'uuid-a'), node('v2', NodeType.PYTHON, 'uuid-b')],
            [node('c1', NodeType.PYTHON, 'uuid-b'), node('same-id', NodeType.PYTHON, 'uuid-c')]
        );

        expect(matching.matches.map((match) => [match.key, match.matchedBy])).toEqual([
            ['version:same-id', null],
            ['uuid:uuid-b', 'uuid'],
            ['current:same-id', null],
        ]);
        expect(matching.versionKeyById.get('v2')).toBe('uuid:uuid-b');
        expect(matching.currentKeyById.get('c1')).toBe('uuid:uuid-b');
    });

    it('never matches nodes without a uuid, or a uuid on nodes of different types', () => {
        const matching = matchNodes(
            [node('v1', NodeType.PYTHON, null), node('v2', NodeType.TABLE, 'uuid-a')],
            [node('c1', NodeType.PYTHON, null), node('c2', NodeType.CLASSIFICATION_TABLE, 'uuid-a')]
        );

        expect(matching.matches.every((match) => match.matchedBy === null)).toBe(true);
    });

    it('pairs Start nodes by type only when the uuid did not pair them', () => {
        const byType = matchNodes(
            [node('v-start', NodeType.START, 'synthetic')],
            [node('c-start', NodeType.START, 'real')]
        );
        const byUuid = matchNodes(
            [node('v-start', NodeType.START, 'real'), node('v-extra-start', NodeType.START, 'other')],
            [node('c-start', NodeType.START, 'real')]
        );

        expect(byType.matches).toEqual([
            expect.objectContaining({ key: 'start', matchedBy: 'start', currentNode: expect.anything() }),
        ]);
        expect(byUuid.matches.map((match) => [match.key, match.matchedBy])).toEqual([
            ['uuid:real', 'uuid'],
            ['version:v-extra-start', null],
        ]);
    });

    it('matches only the first node of a repeated uuid', () => {
        const matching = matchNodes(
            [node('v1', NodeType.PYTHON, 'uuid-a'), node('v2', NodeType.PYTHON, 'uuid-a')],
            [node('c1', NodeType.PYTHON, 'uuid-a'), node('c2', NodeType.PYTHON, 'uuid-a')]
        );

        expect(matching.matches.map((match) => [match.key, match.matchedBy])).toEqual([
            ['uuid:uuid-a', 'uuid'],
            ['version:v2', null],
            ['current:c2', null],
        ]);
    });
});

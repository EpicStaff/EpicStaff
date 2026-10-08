import { NodeType } from '@shared/models';

import { getClassificationTableVisualHeight } from '../helpers/node-size.util';
import { makeNode, tableNode } from '../layout/testing/fixtures';
import { ClassificationDecisionTableNodeModel } from '../models/node.model';
import { obstacleRect, routingObstacles } from './obstacles';

describe('routing obstacles', () => {
    it('pads a plain node by 15 left and right (clear of the port markers) and by 10 above and below', () => {
        const node = makeNode('py', NodeType.PYTHON, { height: 60, position: { x: 100, y: 200 } });

        expect(obstacleRect(node)).toEqual({ left: 85, top: 190, right: 445, bottom: 270 });
    });

    it('pads a table by 20 horizontally, 10 vertically, and uses its visual height after the row count changed', () => {
        // Arranged with 3 rows; 3 more were added since, and size.height was never updated.
        const table = tableNode('cdt', NodeType.CLASSIFICATION_TABLE, 3, {
            x: 0,
            y: 0,
        }) as ClassificationDecisionTableNodeModel;
        const groups = table.data.table.condition_groups;
        const grown = {
            ...table,
            data: { ...table.data, table: { ...table.data.table, condition_groups: [...groups, ...groups] } },
        };
        const visualHeight = getClassificationTableVisualHeight(grown.data.table.condition_groups);

        const rect = obstacleRect(grown);

        expect(visualHeight).toBeGreaterThan(table.size.height);
        expect(rect).toEqual({ left: -20, top: -10, right: 350, bottom: visualHeight + 10 });
    });

    it('leaves NOTE nodes out and keys the rest by id', () => {
        const nodes = [
            makeNode('a', NodeType.PYTHON, { height: 60 }),
            makeNode('note', NodeType.NOTE, { height: 60 }),
            makeNode('b', NodeType.AGENT, { height: 60, position: { x: 500, y: 0 } }),
        ];

        expect([...routingObstacles(nodes).keys()]).toEqual(['a', 'b']);
    });
});

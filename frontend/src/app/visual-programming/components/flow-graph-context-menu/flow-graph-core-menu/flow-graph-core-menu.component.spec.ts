import { TestBed } from '@angular/core/testing';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu.component';

describe('FlowGraphCoreMenuComponent', () => {
    it('lists the persistence node and emits it on click', () => {
        const component = TestBed.runInInjectionContext(() => new FlowGraphCoreMenuComponent());
        const emitted: unknown[] = [];
        component.nodeSelected.subscribe((request) => emitted.push(request));

        expect(component.blocks.find((block) => block.type === NodeType.PERSISTENCE)).toEqual({
            label: 'Persistence',
            type: NodeType.PERSISTENCE,
            icon: NODE_ICONS[NodeType.PERSISTENCE],
            color: NODE_COLORS[NodeType.PERSISTENCE],
        });
        component.onBlockClicked(NodeType.PERSISTENCE);

        expect(emitted).toEqual([{ type: NodeType.PERSISTENCE, data: null }]);
    });
});

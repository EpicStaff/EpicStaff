import { TestBed } from '@angular/core/testing';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu.component';

describe('FlowGraphCoreMenuComponent', () => {
    it('lists the key-value node and emits it on click', () => {
        const component = TestBed.runInInjectionContext(() => new FlowGraphCoreMenuComponent());
        const emitted: unknown[] = [];
        component.nodeSelected.subscribe((request) => emitted.push(request));

        expect(component.blocks.find((block) => block.type === NodeType.KEY_VALUE)).toEqual({
            label: 'Key-Value',
            type: NodeType.KEY_VALUE,
            icon: NODE_ICONS[NodeType.KEY_VALUE],
            color: NODE_COLORS[NodeType.KEY_VALUE],
        });
        component.onBlockClicked(NodeType.KEY_VALUE);

        expect(emitted).toEqual([{ type: NodeType.KEY_VALUE, data: null }]);
    });
});

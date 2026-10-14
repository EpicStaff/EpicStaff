import { TestBed } from '@angular/core/testing';
import { ActionCode, NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu.component';

const TRIGGER_TYPES = [NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER, NodeType.SCHEDULE_TRIGGER];

function createMenu(canRunFlows = true): FlowGraphCoreMenuComponent {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PermissionsService,
                useValue: { can: (_resource: unknown, action: ActionCode) => action !== ActionCode.Run || canRunFlows },
            },
        ],
    });
    return TestBed.runInInjectionContext(() => new FlowGraphCoreMenuComponent());
}

describe('FlowGraphCoreMenuComponent', () => {
    it('lists the key-value node and emits it on click', () => {
        const component = createMenu();
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

    it('offers the trigger nodes to a user who may run flows', () => {
        const offeredTypes = createMenu(true)
            .filteredBlocks()
            .map((block) => block.type);

        expect(offeredTypes).toEqual(expect.arrayContaining(TRIGGER_TYPES));
    });

    it('hides the trigger nodes, and only them, from a user who may update but not run flows', () => {
        const component = createMenu(false);
        const offeredTypes = component.filteredBlocks().map((block) => block.type);

        expect(offeredTypes).toEqual(
            component.blocks.map((block) => block.type).filter((type) => !TRIGGER_TYPES.includes(type))
        );
    });
});

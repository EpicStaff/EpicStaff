import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActionCode, NODE_COLORS, NODE_ICONS, NodeType, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import {
    FLOW_ACTIONS_WITH_USE,
    FLOW_ACTIONS_WITHOUT_USE,
    grantPermissions,
} from '../../../utils/testing/permissions.fixture';
import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu.component';

const TRIGGER_LABELS = ['Webhook Trigger', 'Telegram Trigger', 'Schedule Trigger'];

function createMenu(canRunFlows = true): FlowGraphCoreMenuComponent {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PermissionsService,
                useValue: { can: (_resource: unknown, action: ActionCode) => action !== ActionCode.Use || canRunFlows },
            },
        ],
    });
    return TestBed.runInInjectionContext(() => new FlowGraphCoreMenuComponent());
}

function renderMenu(flowActions = FLOW_ACTIONS_WITH_USE) {
    TestBed.configureTestingModule({ providers: [provideHttpClient()] });
    grantPermissions({ [ResourceCode.Flows]: flowActions });
    const fixture = TestBed.createComponent(FlowGraphCoreMenuComponent);
    fixture.detectChanges();
    return fixture;
}

function offeredLabels(fixture: ReturnType<typeof renderMenu>): string[] {
    return Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('li')).map(
        (item) => item.textContent?.trim() ?? ''
    );
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
        expect(offeredLabels(renderMenu(FLOW_ACTIONS_WITH_USE))).toEqual(expect.arrayContaining(TRIGGER_LABELS));
    });

    it('hides the trigger nodes, and only them, from a user who may update but not run flows', () => {
        const fixture = renderMenu(FLOW_ACTIONS_WITH_USE);
        const offeredWithRun = offeredLabels(fixture);

        grantPermissions({ [ResourceCode.Flows]: FLOW_ACTIONS_WITHOUT_USE });
        fixture.detectChanges();

        expect(offeredLabels(fixture)).toEqual(offeredWithRun.filter((label) => !TRIGGER_LABELS.includes(label)));
    });
});

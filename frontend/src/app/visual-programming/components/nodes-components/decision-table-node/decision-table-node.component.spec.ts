import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { DecisionTableNodeModel } from '../../../core/models/node.model';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { normalizedCssColor, WRONG_APPEARANCE } from '../../../utils/testing/node-appearance.fixture';
import { DecisionTableNodeComponent } from './decision-table-node.component';

describe('DecisionTableNodeComponent header', () => {
    it("renders the type icon and colour, not the node's own", () => {
        TestBed.configureTestingModule({
            providers: [{ provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } }],
        });
        const node = {
            id: 'table',
            backendId: null,
            type: NodeType.TABLE,
            node_name: 'Route',
            data: { name: 'Route', table: { default_next_node: null, next_error_node: null, condition_groups: [] } },
            position: { x: 0, y: 0 },
            ports: [],
            size: { width: 330, height: 120 },
            input_map: {},
            output_variable_path: null,
            ...WRONG_APPEARANCE,
        } as unknown as DecisionTableNodeModel;
        const fixture = TestBed.createComponent(DecisionTableNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();

        const icon: HTMLElement = fixture.nativeElement.querySelector('.icon-wrapper i');

        expect(icon.className).toBe(NODE_ICONS[NodeType.TABLE]);
        expect(icon.style.color).toBe(normalizedCssColor(NODE_COLORS[NodeType.TABLE]));
    });
});

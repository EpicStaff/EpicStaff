import { TestBed } from '@angular/core/testing';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { NodeModel } from '../../../core/models/node.model';
import { WRONG_APPEARANCE } from '../../../utils/testing/node-appearance.fixture';
import { SearchNodeItemComponent } from './search-node-item.component';

describe('SearchNodeItemComponent icon', () => {
    it("shows the type icon and colour, not the node's own", () => {
        const node = {
            id: 'python',
            backendId: null,
            type: NodeType.PYTHON,
            node_name: 'Fetch',
            data: { name: 'Fetch' },
            position: { x: 0, y: 0 },
            ports: [],
            size: { width: 300, height: 200 },
            input_map: {},
            output_variable_path: null,
            ...WRONG_APPEARANCE,
        } as unknown as NodeModel;
        const fixture = TestBed.createComponent(SearchNodeItemComponent);
        fixture.componentInstance.node = node;
        fixture.detectChanges();

        const iconBox: HTMLElement = fixture.nativeElement.querySelector('.node-icon');
        const icon: HTMLElement = iconBox.querySelector('i')!;

        expect(icon.className).toBe(NODE_ICONS[NodeType.PYTHON]);
        expect(iconBox.style.getPropertyValue('--node-color')).toBe(NODE_COLORS[NodeType.PYTHON]);
    });
});

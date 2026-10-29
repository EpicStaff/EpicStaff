import { TestBed } from '@angular/core/testing';
import { NODE_COLORS, NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { WRONG_APPEARANCE } from '../../utils/testing/node-appearance.fixture';
import { FlowNodeVariablesOverlayComponent } from './flow-node-variables-overlay.component';

describe('FlowNodeVariablesOverlayComponent colour', () => {
    // The overlay shows no icon, only the colour of the node's type.
    it("tints the inputs and output overlays with the type colour, not the node's own", () => {
        const node = {
            id: 'agent',
            backendId: null,
            type: NodeType.AGENT,
            node_name: 'Agent',
            data: { name: 'Agent' },
            position: { x: 0, y: 0 },
            ports: [],
            size: { width: 300, height: 200 },
            input_map: { question: 'variables.question' },
            output_variable_path: 'variables.answer',
            ...WRONG_APPEARANCE,
        } as unknown as NodeModel;
        const fixture = TestBed.createComponent(FlowNodeVariablesOverlayComponent);
        fixture.componentRef.setInput('node', node);
        fixture.componentRef.setInput('showVariables', true);
        fixture.detectChanges();

        const overlayColor = (selector: string): string =>
            fixture.nativeElement.querySelector(selector).style.getPropertyValue('--node-overlay-color');

        expect(overlayColor('.inputs-overlay')).toBe(NODE_COLORS[NodeType.AGENT]);
        expect(overlayColor('.output-overlay')).toBe(NODE_COLORS[NodeType.AGENT]);
    });
});

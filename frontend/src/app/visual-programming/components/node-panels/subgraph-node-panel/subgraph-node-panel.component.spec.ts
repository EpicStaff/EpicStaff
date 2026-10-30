import { Component, input } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { GetGraphLightRequest } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { getNodeTitle } from '../../../core/enums/node-title.util';
import { FlowModel } from '../../../core/models/flow.model';
import { SubGraphNodeModel } from '../../../core/models/node.model';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { mapSubGraphNodeToModel } from '../../../utils/load/nodes/subgraph-node.mapper';
import { getNodeDiff } from '../../../utils/save/diff';
import { buildBulkSavePayload } from '../../../utils/save/payload';
import { InputMapComponent } from '../../input-map/input-map.component';
import { SubGraphNodePanelComponent } from './subgraph-node-panel.component';

const FLOWS: GetGraphLightRequest[] = [
    { id: 7, uuid: 'invoices-uuid', name: 'Invoices', description: 'Sends invoices', tags: ['billing'] },
    { id: 8, uuid: 'refunds-uuid', name: 'Refunds', description: '', tags: [] },
];

// The backend nulls `subgraph` once the target flow is deleted; the loader then flags the node.
const BLOCKED_NODE: SubGraphNodeModel = {
    ...mapSubGraphNodeToModel({
        id: 21,
        created_at: '2026-01-01T00:00:00Z',
        node_number: 2,
        node_name: 'Billing',
        graph: 1,
        subgraph: null,
        subgraph_detail: null,
        input_map: { invoice: 'variables.invoice' },
        output_variable_path: 'variables.result',
        metadata: {},
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    }),
    isBlocked: true,
};

// Another node on the canvas, so switching to it rebuilds the panel's form.
const ATTACHED_NODE: SubGraphNodeModel = {
    ...BLOCKED_NODE,
    id: 'attached-node',
    backendId: 22,
    data: { id: 8, uuid: 'refunds-uuid', name: 'Refunds', description: '', tags: [] },
    isBlocked: false,
};

// Stands in for the input map, whose own dependencies (sessions, code runs) are not under test here.
@Component({ selector: 'app-input-map', template: '' })
class InputMapStubComponent {
    readonly activeColor = input<string>();
    readonly readonly = input<boolean>();
}

describe('SubGraphNodePanelComponent', () => {
    let fixture: ComponentFixture<SubGraphNodePanelComponent>;

    const element = (selector: string): HTMLElement | null => fixture.nativeElement.querySelector(selector);
    const missingFlowHint = (): string | undefined => element('.missing-flow-hint')?.textContent?.trim();
    const goToFlowLink = (): HTMLElement => element('.selected-flow-row .go-to-button')!;

    // The Selected Flow dropdown, driven as a user would. Only these two helpers know `app-select`'s DOM.
    const flowSelect = {
        text: (): string => element('.selected-flow-row .selector__text')!.textContent!.trim(),
        choose(name: string): void {
            element('.selected-flow-row .selector__btn')!.click();
            fixture.detectChanges();
            const option = Array.from(document.querySelectorAll<HTMLElement>('.selector__option')).find(
                (candidate) => candidate.textContent!.trim() === name
            )!;
            option.click();
            fixture.detectChanges();
        },
    };

    function open(node: SubGraphNodeModel, { readOnly = false } = {}): SubGraphNodePanelComponent {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowsApiService, useValue: { getGraphsLight: () => of(FLOWS) } },
                {
                    provide: FlowReadOnlyService,
                    useValue: { isNodeTypeReadOnly: () => readOnly, notifyNodeTypeBlocked: () => undefined },
                },
            ],
        });
        TestBed.overrideComponent(SubGraphNodePanelComponent, {
            remove: { imports: [InputMapComponent] },
            add: { imports: [InputMapStubComponent] },
        });
        fixture = TestBed.createComponent(SubGraphNodePanelComponent);
        fixture.componentRef.setInput('node', node);
        fixture.componentRef.setInput('currentFlowId', 1);
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    function showNode(node: SubGraphNodeModel): void {
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    afterEach(() => document.querySelectorAll('.cdk-overlay-container').forEach((overlay) => overlay.remove()));

    describe('on a node whose flow was deleted', () => {
        it('says the flow was deleted and asks for another one, with no flow selected', () => {
            const panel = open(BLOCKED_NODE);

            expect(missingFlowHint()).toBe("This node's flow was deleted. Select another flow.");
            expect(flowSelect.text()).toBe('Select a flow');
            expect(panel.form.get('selectedFlowId')!.hasError('required')).toBe(true);
            expect(goToFlowLink().classList).toContain('disabled');
        });

        it('only says the flow was deleted in a read-only flow', () => {
            open(BLOCKED_NODE, { readOnly: true });

            expect(missingFlowHint()).toBe("This node's flow was deleted.");
        });

        it('saves nothing until a flow is chosen', () => {
            const panel = open(BLOCKED_NODE);

            expect(panel.onSaveSilently()).toBeNull();
        });

        it('attaches the chosen flow and unblocks the node, keeping its name, inputs and output path', () => {
            const panel = open(BLOCKED_NODE);

            flowSelect.choose('Invoices');
            const saved = panel.onSave()!;

            expect(missingFlowHint()).toBeUndefined();
            expect(goToFlowLink().classList).not.toContain('disabled');
            expect(goToFlowLink().getAttribute('href')).toBe('/flows/7');
            expect(saved.data).toEqual(FLOWS[0]);
            expect(saved.isBlocked).toBe(false);
            expect(saved.node_name).toBe('Billing');
            expect(saved.input_map).toEqual({ invoice: 'variables.invoice' });
            expect(saved.output_variable_path).toBe('variables.result');
            expect(getNodeTitle(saved)).toBe('Invoices');
        });

        it('sends the chosen flow as the subgraph of the saved node', () => {
            const panel = open(BLOCKED_NODE);
            flowSelect.choose('Invoices');
            const saved = panel.onSave()!;
            const previous = { nodes: [BLOCKED_NODE], connections: [] } as unknown as FlowModel;
            const current = { nodes: [saved], connections: [] } as unknown as FlowModel;

            const payload = buildBulkSavePayload(
                1,
                getNodeDiff(previous, current),
                { toCreate: [], toDelete: [], toUpdate: [] },
                current,
                new Map(),
                1
            );

            expect(payload['subgraph_node_list']).toEqual([expect.objectContaining({ id: 21, subgraph: 7 })]);
        });
    });

    describe('on a node attached to a flow', () => {
        it('shows its flow and no hint', () => {
            open(ATTACHED_NODE);

            expect(missingFlowHint()).toBeUndefined();
            expect(flowSelect.text()).toBe('Refunds');
            expect(goToFlowLink().getAttribute('href')).toBe('/flows/8');
        });

        it('moves the node to another chosen flow', () => {
            const panel = open(ATTACHED_NODE);

            flowSelect.choose('Invoices');

            expect(panel.onSave()!.data).toEqual(FLOWS[0]);
        });
    });

    describe('when the open panel is given another node', () => {
        it('drops the hint and links to the flow of an attached node', () => {
            open(BLOCKED_NODE);

            showNode(ATTACHED_NODE);

            expect(missingFlowHint()).toBeUndefined();
            expect(goToFlowLink().classList).not.toContain('disabled');
            expect(goToFlowLink().getAttribute('href')).toBe('/flows/8');
        });

        it('shows the hint and disables Go to flow for a node whose flow was deleted', () => {
            open(ATTACHED_NODE);

            showNode(BLOCKED_NODE);

            expect(missingFlowHint()).toBe("This node's flow was deleted. Select another flow.");
            expect(goToFlowLink().classList).toContain('disabled');
        });
    });
});

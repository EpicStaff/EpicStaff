import { getDebugNode, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { FFlowModule } from '@foblex/flow';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { generatePortsForDecisionTableNode } from '../../../core/helpers/helpers';
import { DecisionTableNodeModel } from '../../../core/models/node.model';
import { FlowDiffStateService } from '../../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { mapDecisionTableNodeToModel } from '../../../utils/load/nodes/decision-table-node.mapper';
import { FoblexConnectorStubDirective } from '../../../utils/testing/foblex-connector.stub';
import { liveDecisionTable } from '../../../utils/testing/live-graph.fixture';
import { normalizedCssColor, WRONG_APPEARANCE } from '../../../utils/testing/node-appearance.fixture';
import { DecisionTableNodeComponent } from './decision-table-node.component';

// On a diff canvas, a table on both sides carries the route ports of both; "canvas only" is not in its data.
const table = mapDecisionTableNodeToModel(liveDecisionTable);
const UNION_TABLE: DecisionTableNodeModel = {
    ...table,
    ports: generatePortsForDecisionTableNode(table.id, [
        ...table.data.table.condition_groups,
        { ...table.data.table.condition_groups[0], group_name: 'canvas only' },
    ]),
};
const REMOVED_ROUTE_PORT = `${table.id}_decision-out-canvas-only`;
// Group "yes" is on both sides of the table in the other tests; here only the version has it.
const ADDED_ROUTE_PORT = `${table.id}_decision-out-yes`;

describe('DecisionTableNodeComponent', () => {
    let fixture: ComponentFixture<DecisionTableNodeComponent>;

    function render(diffCanvas: { versionOnlyPortIds: string[]; currentOnlyRoutePortIds?: string[] } | null): void {
        TestBed.configureTestingModule({
            providers: [{ provide: FlowReadOnlyService, useValue: { isReadOnly: signal(true) } }],
        });
        TestBed.overrideComponent(DecisionTableNodeComponent, {
            remove: { imports: [FFlowModule] },
            add: { imports: [FoblexConnectorStubDirective] },
        });
        TestBed.inject(FlowDiffStateService).setState(
            diffCanvas && {
                nodes: new Map([[UNION_TABLE.id, { status: 'changed', fields: [], missingReferences: [] }]]),
                connections: new Map(),
                versionOnlyPortIds: new Set(diffCanvas.versionOnlyPortIds),
                currentOnlyRoutePortIds: new Set(diffCanvas.currentOnlyRoutePortIds ?? []),
                nodeIdByKey: new Map(),
            }
        );
        fixture = TestBed.createComponent(DecisionTableNodeComponent);
        fixture.componentRef.setInput('node', UNION_TABLE);
        fixture.detectChanges();
    }

    const rowOf = (portId: string): HTMLElement | null =>
        fixture.nativeElement.querySelector(`[data-f-output-id="${portId}"]`)?.closest('.decision-table__group') ??
        null;
    const rows = (): HTMLElement[] => [...fixture.nativeElement.querySelectorAll('.decision-table__group')];
    /** The row's own hover tooltip; empty when it has none. */
    const tooltipOf = (row: HTMLElement): string =>
        getDebugNode(row)?.injector.get(MatTooltip, null, { self: true })?.message ?? '';

    it('draws a row with a connector for a route a restore removes, named and labelled for it, on a diff canvas', () => {
        render({ versionOnlyPortIds: [], currentOnlyRoutePortIds: [REMOVED_ROUTE_PORT] });

        const row = rowOf(REMOVED_ROUTE_PORT)!;
        expect(row.textContent?.trim()).toBe('canvas only');
        expect(row.classList).toContain('decision-table__group--removed');
        expect(row.getAttribute('aria-label')).toBe('Restore removes this condition');
        expect(tooltipOf(row)).toBe('Restore removes this condition');
        // The tooltip says what the label says, so a screen reader hears it once (Material describes after render).
        TestBed.tick();
        expect(row.hasAttribute('aria-describedby')).toBe(false);
    });

    it('draws a removed row only for a route the diff says only the current canvas has', () => {
        render({ versionOnlyPortIds: [], currentOnlyRoutePortIds: [] });

        expect(rowOf(REMOVED_ROUTE_PORT)).toBeNull();
        expect(rows().some((row) => row.classList.contains('decision-table__group--removed'))).toBe(false);
    });

    it('marks the row of a route only the version has as one a restore adds, and no other row', () => {
        render({ versionOnlyPortIds: [ADDED_ROUTE_PORT] });

        const addedRow = rowOf(ADDED_ROUTE_PORT)!;
        expect(addedRow.classList).toContain('decision-table__group--added');
        expect(addedRow.getAttribute('aria-label')).toBe('Restore adds this condition');
        expect(tooltipOf(addedRow)).toBe('Restore adds this condition');
        expect(rows().filter((row) => row.classList.contains('decision-table__group--added'))).toEqual([addedRow]);
    });

    it('marks no row and draws no removed route in the live editor', () => {
        render(null);

        expect(rowOf(REMOVED_ROUTE_PORT)).toBeNull();
        for (const row of rows()) {
            expect(row.className).not.toMatch(/--added|--removed/);
            expect(row.hasAttribute('aria-label')).toBe(false);
            expect(tooltipOf(row)).toBe('');
        }
    });
});

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

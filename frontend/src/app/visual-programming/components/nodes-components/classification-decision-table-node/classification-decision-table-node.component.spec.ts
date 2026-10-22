import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FFlowModule } from '@foblex/flow';
import { LlmConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { generatePortsForClassificationDecisionTableNode } from '../../../core/helpers/helpers';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';
import { FlowDiffStateService } from '../../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { mapClassificationDecisionTableNodeToModel } from '../../../utils/load/nodes/classification-decision-table-node.mapper';
import { FoblexConnectorStubDirective } from '../../../utils/testing/foblex-connector.stub';
import { liveClassificationTable } from '../../../utils/testing/live-graph.fixture';
import { ClassificationDecisionTableNodeComponent } from './classification-decision-table-node.component';

// On a diff canvas, a table on both sides carries the route ports of both; route "Route B" is not in its data.
const table = mapClassificationDecisionTableNodeToModel(liveClassificationTable);
const UNION_TABLE: ClassificationDecisionTableNodeModel = {
    ...table,
    ports: generatePortsForClassificationDecisionTableNode(table.id, [
        ...table.data.table.condition_groups,
        { ...table.data.table.condition_groups[0], group_name: 'other', route_code: 'Route B' },
    ]),
};
const REMOVED_ROUTE_PORT = `${table.id}_decision-route-route-b`;
// Route "A" is on both sides of the table in the other tests; here only the version has it.
const ADDED_ROUTE_PORT = `${table.id}_decision-route-a`;

describe('ClassificationDecisionTableNodeComponent', () => {
    let fixture: ComponentFixture<ClassificationDecisionTableNodeComponent>;

    function render(diffCanvas: { versionOnlyPortIds: string[] } | null): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(true) } },
                {
                    provide: LlmConfigStorageService,
                    useValue: { getAllConfigs: () => of([]), isConfigsLoaded: signal(false), configs: signal([]) },
                },
            ],
        });
        TestBed.overrideComponent(ClassificationDecisionTableNodeComponent, {
            remove: { imports: [FFlowModule] },
            add: { imports: [FoblexConnectorStubDirective] },
        });
        TestBed.inject(FlowDiffStateService).setState(
            diffCanvas && {
                nodes: new Map([[UNION_TABLE.id, { status: 'changed', hasMissingReferences: false }]]),
                connections: new Map(),
                versionOnlyPortIds: new Set(diffCanvas.versionOnlyPortIds),
            }
        );
        fixture = TestBed.createComponent(ClassificationDecisionTableNodeComponent);
        fixture.componentRef.setInput('node', UNION_TABLE);
        fixture.detectChanges();
    }

    const rowOf = (portId: string): HTMLElement | null =>
        fixture.nativeElement.querySelector(`[data-f-output-id="${portId}"]`)?.closest('.decision-table__group') ??
        null;
    const rows = (): HTMLElement[] => [...fixture.nativeElement.querySelectorAll('.decision-table__group')];

    it('draws a row with a connector for a route a restore removes, named and labelled for it, on a diff canvas', () => {
        render({ versionOnlyPortIds: [] });

        const row = rowOf(REMOVED_ROUTE_PORT)!;
        expect(row.textContent?.trim()).toBe('Route B');
        expect(row.classList).toContain('decision-table__group--removed');
        expect(row.getAttribute('aria-label')).toBe('Restore removes this condition');
        expect(row.getAttribute('title')).toBe('Restore removes this condition');
    });

    it('marks the row of a route only the version has as one a restore adds, and no other row', () => {
        render({ versionOnlyPortIds: [ADDED_ROUTE_PORT] });

        const addedRow = rowOf(ADDED_ROUTE_PORT)!;
        expect(addedRow.classList).toContain('decision-table__group--added');
        expect(addedRow.getAttribute('aria-label')).toBe('Restore adds this condition');
        expect(addedRow.getAttribute('title')).toBe('Restore adds this condition');
        expect(rows().filter((row) => row.classList.contains('decision-table__group--added'))).toEqual([addedRow]);
    });

    it('marks no row and draws no removed route in the live editor', () => {
        render(null);

        expect(rowOf(REMOVED_ROUTE_PORT)).toBeNull();
        for (const row of rows()) {
            expect(row.className).not.toMatch(/--added|--removed/);
            expect(row.hasAttribute('aria-label')).toBe(false);
            expect(row.hasAttribute('title')).toBe(false);
        }
    });
});

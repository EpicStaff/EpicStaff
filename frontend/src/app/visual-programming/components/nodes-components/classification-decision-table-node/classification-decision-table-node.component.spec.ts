import { getDebugNode, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { FFlowModule } from '@foblex/flow';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';
import { LlmConfigStorageService, SystemOneConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { generatePortsForClassificationDecisionTableNode } from '../../../core/helpers/helpers';
import { PromptConfig } from '../../../core/models/classification-decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { FlowDiffStateService } from '../../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { FlowSettingsService } from '../../../services/flow-settings.service';
import { mapClassificationDecisionTableNodeToModel } from '../../../utils/load/nodes/classification-decision-table-node.mapper';
import { FoblexConnectorStubDirective } from '../../../utils/testing/foblex-connector.stub';
import { liveClassificationTable } from '../../../utils/testing/live-graph.fixture';
import { normalizedCssColor, WRONG_APPEARANCE } from '../../../utils/testing/node-appearance.fixture';
import { ClassificationDecisionTableNodeComponent } from './classification-decision-table-node.component';

// On a diff canvas, a table on both sides carries the route ports of both; route "Route B" is not in its data.
const table = mapClassificationDecisionTableNodeToModel(liveClassificationTable);
const UNION_TABLE: ClassificationDecisionTableNodeModel = {
    ...table,
    ports: generatePortsForClassificationDecisionTableNode(table.id, [
        ...table.data.table.condition_groups,
        { ...table.data.table.condition_groups[0], group_name: 'other', route_code: 'Route B' },
        // The shown side's own group with no route code: it has a port (keyed by its name) but no row.
        { ...table.data.table.condition_groups[0], group_name: 'Condition 5', route_code: null },
    ]),
};
const REMOVED_ROUTE_PORT = `${table.id}_decision-route-route-b`;
const ROWLESS_SHOWN_PORT = `${table.id}_decision-route-condition-5`;
// Route "A" is on both sides of the table in the other tests; here only the version has it.
const ADDED_ROUTE_PORT = `${table.id}_decision-route-a`;

describe('ClassificationDecisionTableNodeComponent', () => {
    let fixture: ComponentFixture<ClassificationDecisionTableNodeComponent>;

    function render(diffCanvas: { versionOnlyPortIds: string[]; currentOnlyRoutePortIds?: string[] } | null): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(true) } },
                {
                    provide: LlmConfigStorageService,
                    useValue: { getAllConfigs: () => of([]), isConfigsLoaded: signal(false), configs: signal([]) },
                },
                {
                    provide: SystemOneConfigStorageService,
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
                nodes: new Map([[UNION_TABLE.id, { status: 'changed', fields: [], missingReferences: [] }]]),
                connections: new Map(),
                versionOnlyPortIds: new Set(diffCanvas.versionOnlyPortIds),
                currentOnlyRoutePortIds: new Set(diffCanvas.currentOnlyRoutePortIds ?? []),
                nodeIdByKey: new Map(),
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
    /** The row's own hover tooltip; empty when it has none. */
    const tooltipOf = (row: HTMLElement): string =>
        getDebugNode(row)?.injector.get(MatTooltip, null, { self: true })?.message ?? '';

    it('draws a row with a connector for a route a restore removes, named and labelled for it, on a diff canvas', () => {
        render({ versionOnlyPortIds: [], currentOnlyRoutePortIds: [REMOVED_ROUTE_PORT] });

        const row = rowOf(REMOVED_ROUTE_PORT)!;
        expect(row.textContent?.trim()).toBe('Route B');
        expect(row.classList).toContain('decision-table__group--removed');
        expect(row.getAttribute('aria-label')).toBe('Restore removes this condition');
        expect(tooltipOf(row)).toBe('Restore removes this condition');
        // The tooltip says what the label says, so a screen reader hears it once (Material describes after render).
        TestBed.tick();
        expect(row.hasAttribute('aria-describedby')).toBe(false);
    });

    it('draws no removed row for a group of its own without a route code, which has a port but no row', () => {
        render({ versionOnlyPortIds: [], currentOnlyRoutePortIds: [REMOVED_ROUTE_PORT] });

        expect(UNION_TABLE.ports!.some((port) => port.id === ROWLESS_SHOWN_PORT)).toBe(true);
        expect(rowOf(ROWLESS_SHOWN_PORT)).toBeNull();
        expect(rows().filter((row) => row.classList.contains('decision-table__group--removed'))).toEqual([
            rowOf(REMOVED_ROUTE_PORT),
        ]);
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

describe('ClassificationDecisionTableNodeComponent header', () => {
    it("renders the type icon and colour, not the node's own", () => {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } },
                {
                    provide: LlmConfigStorageService,
                    useValue: { isConfigsLoaded: signal(false), configs: signal([]), getAllConfigs: () => of([]) },
                },
                {
                    provide: SystemOneConfigStorageService,
                    useValue: { isConfigsLoaded: signal(false), configs: signal([]), getAllConfigs: () => of([]) },
                },
            ],
        });
        const node = {
            id: 'classification',
            backendId: null,
            type: NodeType.CLASSIFICATION_TABLE,
            node_name: 'Route',
            data: { name: 'Route', table: { default_next_node: null, next_error_node: null, condition_groups: [] } },
            position: { x: 0, y: 0 },
            ports: [],
            size: { width: 330, height: 120 },
            input_map: {},
            output_variable_path: null,
            ...WRONG_APPEARANCE,
        } as unknown as ClassificationDecisionTableNodeModel;
        const fixture = TestBed.createComponent(ClassificationDecisionTableNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();

        const icon: HTMLElement = fixture.nativeElement.querySelector('.icon-wrapper i');

        expect(icon.className).toBe(NODE_ICONS[NodeType.CLASSIFICATION_TABLE]);
        expect(icon.style.color).toBe(normalizedCssColor(NODE_COLORS[NodeType.CLASSIFICATION_TABLE]));
    });
});

const SYSTEM_ONE_MESSAGE = 'A System One entry needs a config';
const LLM_MESSAGE = 'LLM config is missing or was deleted';

describe('ClassificationDecisionTableNodeComponent config warnings', () => {
    const systemOneConfigs = signal<{ id: number }[]>([]);
    const systemOneLoaded = signal(false);

    function nodeWith(prompts: Record<string, PromptConfig>): ClassificationDecisionTableNodeModel {
        return {
            data: { table: { prompts, condition_groups: [], default_llm_config: null } },
        } as unknown as ClassificationDecisionTableNodeModel;
    }

    function llmPrompt(llmConfig: number | null): PromptConfig {
        return {
            prompt_text: 'Classify',
            llm_config: llmConfig,
            output_schema: null,
            result_variable: 'category',
            variable_mappings: {},
        };
    }

    function systemOnePrompt(config: number | null): PromptConfig {
        return { ...llmPrompt(null), kind: 'system_one', system_one_config: config };
    }

    function messagesFor(prompts: Record<string, PromptConfig>): string[] {
        const component = TestBed.runInInjectionContext(() => new ClassificationDecisionTableNodeComponent());
        component.node = nodeWith(prompts);
        return component.errorMessages;
    }

    beforeEach(() => {
        systemOneConfigs.set([{ id: 7 }]);
        systemOneLoaded.set(true);
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowService, useValue: {} },
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } },
                { provide: FlowSettingsService, useValue: {} },
                {
                    provide: LlmConfigStorageService,
                    useValue: {
                        getAllConfigs: () => of([]),
                        configs: signal([{ id: 2 }]),
                        isConfigsLoaded: signal(true),
                    },
                },
                {
                    provide: SystemOneConfigStorageService,
                    useValue: {
                        getAllConfigs: () => of([]),
                        configs: systemOneConfigs,
                        isConfigsLoaded: systemOneLoaded,
                    },
                },
            ],
        });
    });

    it('warns about a System One entry with no config', () => {
        expect(messagesFor({ check: systemOnePrompt(null) })).toEqual([SYSTEM_ONE_MESSAGE]);
    });

    it('does not warn about a System One entry whose config exists', () => {
        expect(messagesFor({ check: systemOnePrompt(7) })).toEqual([]);
    });

    it('warns about a System One entry whose config was deleted', () => {
        expect(messagesFor({ check: systemOnePrompt(8) })).toEqual([SYSTEM_ONE_MESSAGE]);
    });

    it('does not call a System One config deleted before the configs have loaded', () => {
        systemOneLoaded.set(false);
        systemOneConfigs.set([]);

        expect(messagesFor({ check: systemOnePrompt(8) })).toEqual([]);
    });

    it('never raises the LLM warning for a System One entry', () => {
        expect(messagesFor({ check: systemOnePrompt(7) })).not.toContain(LLM_MESSAGE);
    });

    it('still raises the LLM warning for an LLM prompt with no LLM', () => {
        expect(messagesFor({ check: llmPrompt(null) })).toEqual([LLM_MESSAGE]);
    });
});

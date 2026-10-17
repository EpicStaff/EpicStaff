import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NODE_COLORS, NodeType } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../features/agent-definitions/services/agent-definitions-api.service';
import { KeyValueTablesStorageService } from '../../../features/key-value-tables/services/key-value-tables-storage.service';
import { KeyValueMode } from '../../core/models/key-value-node.model';
import { DecisionTableNodeModel, NodeModel } from '../../core/models/node.model';
import { FlowService } from '../../services/flow.service';
import { FlowReadOnlyService } from '../../services/flow-readonly.service';
import { mapKeyValueNodeToModel } from '../../utils/load/nodes/key-value-node.mapper';
import { mapStartNodeToModel } from '../../utils/load/nodes/start-node.mapper';
import { FlowBaseNodeComponent } from './flow-base-node.component';

const KEY_VALUE_NODE = {
    ...mapKeyValueNodeToModel({
        id: 12,
        graph: 1,
        node_number: 1,
        node_name: 'Key-Value',
        key_value_table: 3,
        mode: 'write',
        entries: [
            { key: 'profile', value: 'variables.user' },
            { key: 'plan', value: 'variables.plan' },
        ],
        input_map: {},
        output_variable_path: null,
        metadata: {},
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    }),
    nodeNumber: 1,
};

describe('FlowBaseNodeComponent key-value summary', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;

    const summaryTab = (): HTMLElement | null => fixture.nativeElement.querySelector('.node-number-badge.has-summary');
    const summaryParts = (): string[] =>
        Array.from<HTMLElement>(summaryTab()!.querySelectorAll('.summary > span:not(.summary-separator)')).map((part) =>
            part.textContent!.trim()
        );
    const separators = (): string[] =>
        Array.from<HTMLElement>(summaryTab()!.querySelectorAll('.summary-separator')).map((separator) =>
            separator.textContent!.trim()
        );
    const noTableBadge = (): HTMLElement | undefined =>
        Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.llm-warning-badge')).find(
            (badge) => badge.textContent!.trim() === 'No table'
        );

    function render(node: NodeModel, readOnly = false): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(readOnly) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                {
                    provide: KeyValueTablesStorageService,
                    useValue: {
                        tables: signal([{ id: 3, name: 'Very very long table name' }]),
                        loadTables: () => of([]),
                    },
                },
            ],
        });
        fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    it('sums up mode, table and keys after the node number, the table name cut short, in full on hover', () => {
        render(KEY_VALUE_NODE);

        expect(summaryTab()!.querySelector('.node-number')!.textContent!.trim()).toBe('#1');
        expect(summaryParts()).toEqual(['Write', 'Very very long tabl…', '2 keys']);
        expect(separators()).toEqual(['-', '/', '/']);
        expect(summaryTab()!.title).toBe('Write / Very very long table name / 2 keys');
    });

    it('reads the summary once to screen readers, from the header icon, with the table name in full', () => {
        render(KEY_VALUE_NODE);

        expect(summaryTab()!.querySelector('.summary')!.getAttribute('aria-hidden')).toBe('true');
        expect(summaryTab()!.querySelector('.node-number')!.closest('[aria-hidden]')).toBeNull();
        expect(fixture.nativeElement.querySelector('.icon-wrapper [role="img"]').getAttribute('aria-label')).toBe(
            'Write / Very very long table name / 2 keys'
        );
    });

    const MODE_STRIPES: Record<KeyValueMode, string> = {
        read: 'var(--success-color)',
        write: 'var(--color-status-processing)',
        delete: 'var(--color-status-error)',
    };
    for (const mode of Object.keys(MODE_STRIPES) as KeyValueMode[]) {
        it(`draws the type's database icon in its colour in ${mode}, with the mode only on the left stripe`, () => {
            // Neither a saved icon nor a saved colour is what the header shows.
            render({
                ...KEY_VALUE_NODE,
                icon: 'ti ti-database-x',
                color: '#000000',
                data: { ...KEY_VALUE_NODE.data, mode },
            });
            const icon: HTMLElement = fixture.nativeElement.querySelector('.icon-wrapper i');
            const typeColor = document.createElement('i');
            typeColor.style.color = NODE_COLORS[NodeType.KEY_VALUE];

            expect(icon.className).toBe('ti ti-database');
            expect(icon.style.color).toBe(typeColor.style.color);
            expect(
                fixture.nativeElement
                    .querySelector('.interactive-node-body')
                    .style.getPropertyValue('--key-value-accent')
            ).toBe(MODE_STRIPES[mode]);
        });
    }

    const NO_TABLE_NODE = { ...KEY_VALUE_NODE, data: { ...KEY_VALUE_NODE.data, key_value_table: null } };

    it('flags a node without a table and says where to pick one', () => {
        render(NO_TABLE_NODE);

        expect(noTableBadge()!.title).toBe('Select a table in the node panel');
    });

    it('flags a node without a table in a read-only flow without asking to pick one', () => {
        render(NO_TABLE_NODE, true);

        expect(noTableBadge()!.title).toBe('No table selected');
    });

    it('is only for key-value nodes', () => {
        render({
            ...mapStartNodeToModel({
                id: 1,
                created_at: '2026-01-01T00:00:00Z',
                graph: 1,
                node_name: '__start__',
                variables: {},
                metadata: {},
                created_by: null,
                last_edited_by: null,
                last_edited_at: null,
            }),
            ports: null,
        });

        expect(summaryTab()).toBeNull();
    });
});

describe('FlowBaseNodeComponent node number', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;

    const text = (selector: string): string => fixture.nativeElement.querySelector(selector)!.textContent!.trim();

    function render(node: NodeModel, otherNodes: NodeModel[] = []): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                {
                    provide: KeyValueTablesStorageService,
                    useValue: { tables: signal([]), loadTables: () => of([]) },
                },
            ],
        });
        TestBed.inject(FlowService).setFlow({ nodes: [node, ...otherNodes], connections: [] });
        fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    it('titles the node with its name and shows the number only in the badge', () => {
        render({ ...KEY_VALUE_NODE, nodeNumber: 3 });

        expect(text('.interactive-node-body .title')).toBe('Key-Value');
        expect(text('.node-number')).toBe('#3');
    });

    describe('on a decision table', () => {
        const fetchNode = { id: 'fetch', type: NodeType.PYTHON, node_name: 'Fetch', nodeNumber: 4 } as NodeModel;
        const tableNode = {
            id: 'table',
            backendId: null,
            type: NodeType.TABLE,
            node_name: 'Route',
            nodeNumber: 3,
            data: {
                name: 'Route',
                table: { default_next_node: 'fetch', next_error_node: null, condition_groups: [] },
            },
            position: { x: 0, y: 0 },
            ports: [],
            color: '',
            icon: '',
            size: { width: 300, height: 200 },
            input_map: {},
            output_variable_path: null,
        } as unknown as DecisionTableNodeModel;

        it('titles the table with its name and shows the number only in the badge', () => {
            render(tableNode, [fetchNode]);

            expect(text('.decision-table__header .title')).toBe('Route');
            expect(text('.node-number-badge')).toBe('#3');
        });

        it('names the next node with its number, so same-named nodes are told apart', () => {
            render(tableNode, [fetchNode, { ...fetchNode, id: 'fetch-again', nodeNumber: 9 }]);

            expect(text('.decision-table__group .group-status')).toBe('(Fetch #4)');
        });
    });
});

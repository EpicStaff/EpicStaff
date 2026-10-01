import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NODE_COLORS, NodeType } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../features/agent-definitions/services/agent-definitions-api.service';
import { KeyValueTablesStorageService } from '../../../features/key-value-tables/services/key-value-tables-storage.service';
import { KeyValueMode } from '../../core/models/key-value-node.model';
import { NodeModel } from '../../core/models/node.model';
import { FlowReadOnlyService } from '../../services/flow-readonly.service';
import { mapKeyValueNodeToModel } from '../../utils/load/nodes/key-value-node.mapper';
import { mapStartNodeToModel } from '../../utils/load/nodes/start-node.mapper';
import { FlowBaseNodeComponent } from './flow-base-node.component';

const KEY_VALUE_NODE = mapKeyValueNodeToModel({
    id: 12,
    graph: 1,
    node_name: 'Key-Value #1',
    key_value_table: 3,
    mode: 'write',
    entries: [
        { key: 'profile', value: 'variables.user' },
        { key: 'plan', value: 'variables.plan' },
    ],
    input_map: {},
    output_variable_path: null,
    metadata: {},
});

describe('FlowBaseNodeComponent key-value caption', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;

    const caption = (): HTMLElement | null => fixture.nativeElement.querySelector('.key-value-caption');
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

    it('sums up mode, table and keys under the node, the table name cut short, in full on hover of the caption', () => {
        render(KEY_VALUE_NODE);

        expect(caption()!.textContent!.trim()).toBe('Write · Very very long tabl… · 2 keys');
        expect(caption()!.title).toBe('Write · Very very long table name · 2 keys');
        // Screen readers get the summary once, from the header icon.
        expect(caption()!.getAttribute('aria-hidden')).toBe('true');
        expect(fixture.nativeElement.querySelector('.icon-wrapper [role="img"]').getAttribute('aria-label')).toBe(
            'Write · Very very long table name · 2 keys'
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
            ...mapStartNodeToModel({ id: 1, graph: 1, node_name: '__start__', variables: {}, metadata: {} }),
            ports: null,
        });

        expect(caption()).toBeNull();
    });
});

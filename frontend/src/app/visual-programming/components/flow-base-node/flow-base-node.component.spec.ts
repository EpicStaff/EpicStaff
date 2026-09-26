import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LlmConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../features/agent-definitions/services/agent-definitions-api.service';
import { PersistenceTablesStorageService } from '../../../features/persistent-data/services/persistence-tables-storage.service';
import { NodeModel } from '../../core/models/node.model';
import { mapPersistenceNodeToModel } from '../../utils/load/nodes/persistence-node.mapper';
import { mapStartNodeToModel } from '../../utils/load/nodes/start-node.mapper';
import { FlowBaseNodeComponent } from './flow-base-node.component';

const PERSISTENCE_NODE = mapPersistenceNodeToModel({
    id: 12,
    graph: 1,
    node_name: 'Persistence #1',
    persistence_table: 3,
    mode: 'write',
    entries: [
        { key: 'profile', value: 'variables.user' },
        { key: 'plan', value: 'variables.plan' },
    ],
    input_map: {},
    output_variable_path: null,
    metadata: {},
});

describe('FlowBaseNodeComponent persistence caption', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;

    const caption = (): HTMLElement | null => fixture.nativeElement.querySelector('.persistence-caption');

    function render(node: NodeModel): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                {
                    provide: PersistenceTablesStorageService,
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
        render(PERSISTENCE_NODE);

        expect(caption()!.textContent!.trim()).toBe('Write · Very very long tabl… · 2 keys');
        expect(caption()!.title).toBe('Write · Very very long table name · 2 keys');
        // Screen readers get the summary once, from the header icon.
        expect(caption()!.getAttribute('aria-hidden')).toBe('true');
        expect(fixture.nativeElement.querySelector('.icon-wrapper [role="img"]').getAttribute('aria-label')).toBe(
            'Write · Very very long table name · 2 keys'
        );
    });

    it('is only for persistence nodes', () => {
        render({
            ...mapStartNodeToModel({ id: 1, graph: 1, node_name: '__start__', variables: {}, metadata: {} }),
            ports: null,
        });

        expect(caption()).toBeNull();
    });
});

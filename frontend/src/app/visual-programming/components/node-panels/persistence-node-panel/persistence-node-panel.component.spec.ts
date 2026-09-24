import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormArray } from '@angular/forms';
import { NEVER, of } from 'rxjs';

import { PersistenceTablesApiService } from '../../../../features/persistent-data/services/persistence-tables-api.service';
import { PersistenceTablesStorageService } from '../../../../features/persistent-data/services/persistence-tables-storage.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { FlowModel } from '../../../core/models/flow.model';
import { PersistenceNodeModel } from '../../../core/models/node.model';
import { GetPersistenceNodeRequest } from '../../../core/models/persistence-node.model';
import { SidePanelService } from '../../../services/side-panel.service';
import { UniqueNodeNameValidatorService } from '../../../services/unique-node-name.validator';
import { mapPersistenceNodeToModel } from '../../../utils/load/nodes/persistence-node.mapper';
import { getNodeDiff } from '../../../utils/save/diff';
import { PersistenceNodePanelComponent } from './persistence-node-panel.component';

const DTO: GetPersistenceNodeRequest = {
    id: 12,
    graph: 1,
    node_name: 'Persistence #1',
    persistence_table: 3,
    mode: 'read',
    // jsonb key order: shorter keys first.
    entries: [
        { key: 'profile', alias: 'user', default: { tier: 'free' } },
        { key: 'plan', alias: 'plan' },
    ],
    input_map: {},
    output_variable_path: 'variables.saved',
    metadata: {},
};

function createPanel(node: PersistenceNodeModel): {
    panel: PersistenceNodePanelComponent;
    triggerAutosave: ReturnType<typeof vi.fn>;
} {
    const triggerAutosave = vi.fn();
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PersistenceTablesApiService,
                useValue: { lookupEntries: () => of({}), getEntries: () => NEVER },
            },
            { provide: PersistenceTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
            { provide: PermissionsService, useValue: { can: () => false } },
            {
                provide: UniqueNodeNameValidatorService,
                useValue: { createSyncUniqueNameValidator: () => () => null, getValidationErrorMessage: () => '' },
            },
            { provide: SidePanelService, useValue: { triggerAutosave } },
        ],
    });
    TestBed.overrideComponent(PersistenceNodePanelComponent, { set: { template: '', imports: [] } });
    const fixture = TestBed.createComponent(PersistenceNodePanelComponent);
    fixture.componentRef.setInput('node', node);
    fixture.detectChanges();
    return { panel: fixture.componentInstance, triggerAutosave };
}

function flowOf(node: PersistenceNodeModel): FlowModel {
    return { nodes: [node], connections: [] } as unknown as FlowModel;
}

describe('PersistenceNodePanelComponent', () => {
    afterEach(() => vi.useRealTimers());

    it('does not turn an unchanged read node loaded in jsonb key order into an update', () => {
        const loaded = mapPersistenceNodeToModel(DTO);
        const { panel } = createPanel(loaded);

        const saved = panel.onSave();

        expect(saved).not.toBeNull();
        expect(getNodeDiff(flowOf(loaded), flowOf(saved!)).persistenceNodes.toUpdate).toEqual([]);
    });

    it('asks for a debounced autosave when mode or table change, so the canvas badge follows', () => {
        vi.useFakeTimers();
        const { panel, triggerAutosave } = createPanel(
            mapPersistenceNodeToModel({ ...DTO, mode: 'write', entries: [{ key: 'profile', value: 'user' }] })
        );

        panel.form.get('mode')!.setValue('delete');
        expect(triggerAutosave).not.toHaveBeenCalled();
        vi.advanceTimersByTime(300);
        expect(triggerAutosave).toHaveBeenCalledTimes(1);

        panel.form.get('persistence_table')!.setValue(4);
        vi.advanceTimersByTime(300);
        expect(triggerAutosave).toHaveBeenCalledTimes(2);

        // What removeEntry() does.
        (panel.form.get('entries') as FormArray).removeAt(0);
        vi.advanceTimersByTime(300);
        expect(triggerAutosave).toHaveBeenCalledTimes(3);
    });

    it('does not autosave for edits the canvas does not show', () => {
        vi.useFakeTimers();
        const { panel, triggerAutosave } = createPanel(mapPersistenceNodeToModel(DTO));

        panel.form.get('node_name')!.setValue('Renamed');
        panel.form.get('output_variable_path')!.setValue('variables.other');
        vi.advanceTimersByTime(300);

        expect(triggerAutosave).not.toHaveBeenCalled();
    });
});

import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, FormArray, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
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

// Stands in for the form-bound shared controls so the real template renders without their dependencies.
@Component({
    selector: 'app-select, app-custom-input',
    template: '',
    providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => FormControlStubComponent), multi: true }],
})
class FormControlStubComponent implements ControlValueAccessor {
    writeValue(): void {}
    registerOnChange(): void {}
    registerOnTouched(): void {}
}

function createPanel(
    node: PersistenceNodeModel,
    { renderTemplate = false }: { renderTemplate?: boolean } = {}
): {
    panel: PersistenceNodePanelComponent;
    fixture: ComponentFixture<PersistenceNodePanelComponent>;
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
    TestBed.overrideComponent(PersistenceNodePanelComponent, {
        set: renderTemplate
            ? { imports: [ReactiveFormsModule, FormControlStubComponent], schemas: [CUSTOM_ELEMENTS_SCHEMA] }
            : { template: '', imports: [] },
    });
    const fixture = TestBed.createComponent(PersistenceNodePanelComponent);
    fixture.componentRef.setInput('node', node);
    fixture.detectChanges();
    return { panel: fixture.componentInstance, fixture, triggerAutosave };
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
            mapPersistenceNodeToModel({ ...DTO, mode: 'write', entries: [{ key: 'profile', value: 'variables.user' }] })
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

    it('has no input map section and saves an empty input map', () => {
        const { panel, fixture } = createPanel(
            mapPersistenceNodeToModel({ ...DTO, input_map: { user_id: 'variables.user.id' } }),
            { renderTemplate: true }
        );

        expect(fixture.nativeElement.querySelector('app-input-map')).toBeNull();
        expect(panel.onSave()!.input_map).toEqual({});
    });

    it('accepts only state paths as write values', () => {
        const { panel } = createPanel(
            mapPersistenceNodeToModel({ ...DTO, mode: 'write', entries: [{ key: 'profile', value: '' }] })
        );
        const value = (panel.form.get('entries') as FormArray).at(0).get('value')!;

        for (const path of ['variables.a.b', 'variables.x|0', 'variables[0]', ' variables.a ']) {
            value.setValue(path);
            expect(value.valid).toBe(true);
        }
        for (const path of ['name', 'variables', 'variables.', '   ']) {
            value.setValue(path);
            expect(value.hasError('pattern')).toBe(true);
        }
        value.setValue('');
        expect(value.hasError('required')).toBe(true);
    });

    it('shows an inline error for a write value that is not a state path, and saves it trimmed', () => {
        const { panel, fixture } = createPanel(
            mapPersistenceNodeToModel({ ...DTO, mode: 'write', entries: [{ key: 'profile', value: 'variables.a' }] }),
            { renderTemplate: true }
        );
        const value = (panel.form.get('entries') as FormArray).at(0).get('value')!;
        const hintText = (): string | undefined =>
            fixture.nativeElement.querySelector('.entry-hint')?.textContent.trim();

        value.setValue('name');
        fixture.detectChanges();
        expect(hintText()).toBe('Must be a state path, e.g. variables.user.name');

        value.setValue('  variables.user.name ');
        fixture.detectChanges();
        expect(hintText()).toBeUndefined();
        expect(panel.onSave()!.data.entries).toEqual([{ key: 'profile', value: 'variables.user.name' }]);
    });

    it('hints at key placeholders that are not state paths', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });
        const entries = panel.form.get('entries') as FormArray;
        const hints = (): string[] =>
            Array.from(fixture.nativeElement.querySelectorAll('.entry-hint'), (hint: Element) =>
                hint.textContent!.trim()
            );

        entries.at(0).patchValue({ key: 'profile_{user_id}' });
        entries.at(1).patchValue({ key: 'plan_{ variables.user.id }' });
        fixture.detectChanges();

        expect(hints()).toEqual(['Not a state path: {user_id}. Use e.g. {variables.user.id}']);

        entries.at(1).patchValue({ key: 'plan_{}' });
        fixture.detectChanges();

        expect(hints()).toEqual([
            'Not a state path: {user_id}. Use e.g. {variables.user.id}',
            'Empty or unbalanced placeholder. Use e.g. {variables.user.id}',
        ]);
    });

    it('drops read aliases when switching to write, leaving the value path empty', () => {
        const { panel } = createPanel(mapPersistenceNodeToModel(DTO));

        panel.form.get('mode')!.setValue('write');

        const entries = panel.form.get('entries') as FormArray;
        expect(entries.getRawValue()).toEqual([
            { key: 'profile', value: '' },
            { key: 'plan', value: '' },
        ]);
        expect(entries.at(0).get('value')!.hasError('required')).toBe(true);
    });

    describe('output variable path', () => {
        const writeNode = (): PersistenceNodeModel =>
            mapPersistenceNodeToModel({
                ...DTO,
                mode: 'write',
                entries: [{ key: 'profile', value: 'variables.user' }],
            });
        const outputField = (fixture: ComponentFixture<PersistenceNodePanelComponent>): Element | null =>
            fixture.nativeElement.querySelector('app-custom-input[label="Output Variable Path"]');

        it('is shown and saved in read mode', () => {
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });

            expect(outputField(fixture)).not.toBeNull();
            expect(panel.onSave()!.output_variable_path).toBe('variables.saved');
        });

        it('is hidden in write mode and saved as null even when the node had one', () => {
            const { panel, fixture } = createPanel(writeNode(), { renderTemplate: true });

            expect(outputField(fixture)).toBeNull();
            expect(panel.onSave()!.output_variable_path).toBeNull();
        });

        it('disappears when the mode switches from read to write', () => {
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });

            panel.form.get('mode')!.setValue('write');
            // Write entries need a value path before the form is valid.
            (panel.form.get('entries') as FormArray).controls.forEach((entry) =>
                entry.patchValue({ value: 'variables.user' })
            );
            fixture.detectChanges();

            expect(outputField(fixture)).toBeNull();
            expect(panel.onSave()!.output_variable_path).toBeNull();
        });
    });
});

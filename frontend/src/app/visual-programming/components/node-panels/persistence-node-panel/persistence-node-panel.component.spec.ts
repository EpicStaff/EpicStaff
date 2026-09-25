import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
    AbstractControl,
    ControlValueAccessor,
    FormArray,
    NG_VALUE_ACCESSOR,
    ReactiveFormsModule,
} from '@angular/forms';
import { NEVER, Observable, of, Subject } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { PersistenceTableEntry } from '../../../../features/persistent-data/models/persistence-table.model';
import { PersistenceTablesApiService } from '../../../../features/persistent-data/services/persistence-tables-api.service';
import { PersistenceTablesStorageService } from '../../../../features/persistent-data/services/persistence-tables-storage.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { FlowModel } from '../../../core/models/flow.model';
import { PersistenceNodeModel } from '../../../core/models/node.model';
import { GetPersistenceNodeRequest, PersistenceMode } from '../../../core/models/persistence-node.model';
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
    {
        renderTemplate = false,
        canRead = false,
        getEntries = () => NEVER,
    }: {
        renderTemplate?: boolean;
        canRead?: boolean;
        getEntries?: () => Observable<ApiGetRequest<PersistenceTableEntry>>;
    } = {}
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
                useValue: { lookupEntries: () => of({}), getEntries },
            },
            { provide: PersistenceTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
            { provide: PermissionsService, useValue: { can: () => canRead } },
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

    it('says how to fix a write value that is not a state path, and saves it trimmed', () => {
        const { panel, fixture } = createPanel(
            mapPersistenceNodeToModel({ ...DTO, mode: 'write', entries: [{ key: 'profile', value: 'variables.a' }] }),
            { renderTemplate: true }
        );
        const value = (panel.form.get('entries') as FormArray).at(0).get('value')!;
        const hintText = (): string | undefined =>
            fixture.nativeElement.querySelector('.entry-hint')?.textContent.trim();

        value.setValue('user.name');
        fixture.detectChanges();
        expect(hintText()).toBe('Use variables.user.name');

        value.setValue('user name');
        fixture.detectChanges();
        expect(hintText()).toBe('Use a state path like variables.user.name');

        value.setValue('  variables.user.name ');
        fixture.detectChanges();
        expect(hintText()).toBeUndefined();
        expect(panel.onSave()!.data.entries).toEqual([{ key: 'profile', value: 'variables.user.name' }]);
    });

    it('says how to write key placeholders, building the fix from what was typed', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });
        const entries = panel.form.get('entries') as FormArray;
        const hints = (): string[] =>
            Array.from(fixture.nativeElement.querySelectorAll('.entry-hint'), (hint: Element) =>
                hint.textContent!.trim()
            );

        entries.at(0).patchValue({ key: 'profile_{user_id}' });
        entries.at(1).patchValue({ key: 'plan_{ variables.user.id }' });
        fixture.detectChanges();

        expect(hints()).toEqual(['Use {variables.user_id}']);

        entries.at(1).patchValue({ key: 'plan_{}' });
        fixture.detectChanges();

        expect(hints()).toEqual(['Use {variables.user_id}', 'Write placeholders as {variables.user.id}']);
    });

    it('drops read aliases when switching to write, prefilling the value path without an error yet', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });

        panel.form.get('mode')!.setValue('write');
        fixture.detectChanges();

        const entries = panel.form.get('entries') as FormArray;
        expect(entries.getRawValue()).toEqual([
            { key: 'profile', value: 'variables.' },
            { key: 'plan', value: 'variables.' },
        ]);
        expect(entries.at(0).get('value')!.hasError('pattern')).toBe(true);
        expect(fixture.nativeElement.querySelector('.entry-hint')).toBeNull();
    });

    it('prefills the value of a new write entry and shows its hint only once touched', () => {
        const { panel, fixture } = createPanel(
            mapPersistenceNodeToModel({ ...DTO, mode: 'write', entries: [{ key: 'profile', value: 'variables.a' }] }),
            { renderTemplate: true }
        );

        fixture.nativeElement.querySelector('.add-entry').click();
        fixture.detectChanges();

        const added = (panel.form.get('entries') as FormArray).at(1);
        expect(added.value).toEqual({ key: '', value: 'variables.' });
        // A key makes the row count, so its prefilled value is now checked.
        added.patchValue({ key: 'plan' });
        fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('.entry-hint')).toBeNull();

        added.get('value')!.markAsTouched();
        fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('.entry-hint').textContent.trim()).toBe(
            'Use a state path like variables.user.name'
        );
    });

    describe('empty entries', () => {
        const nodes: Record<PersistenceMode, PersistenceNodeModel> = {
            read: mapPersistenceNodeToModel({ ...DTO, entries: [{ key: 'plan', alias: 'plan' }] }),
            write: mapPersistenceNodeToModel({
                ...DTO,
                mode: 'write',
                entries: [{ key: 'plan', value: 'variables.plan' }],
            }),
            delete: mapPersistenceNodeToModel({ ...DTO, mode: 'delete', entries: [{ key: 'plan' }] }),
        };
        const addEntry = (
            fixture: ComponentFixture<PersistenceNodePanelComponent>,
            panel: PersistenceNodePanelComponent
        ): AbstractControl => {
            fixture.nativeElement.querySelector('.add-entry').click();
            fixture.detectChanges();
            const entries = panel.form.get('entries') as FormArray;
            return entries.at(entries.length - 1);
        };

        for (const mode of ['read', 'write', 'delete'] as const) {
            it(`does not block the save of a ${mode} node and is left out of its entries`, () => {
                const { panel, fixture } = createPanel(nodes[mode], { renderTemplate: true });
                const saved = nodes[mode].data.entries;

                const added = addEntry(fixture, panel);
                added.markAllAsTouched();

                expect(panel.form.valid).toBe(true);
                expect(panel.onSave()!.data.entries).toEqual(saved);
                expect(panel.onSaveSilently()!.data.entries).toEqual(saved);
                // Still in the form: the user is about to type into it.
                expect((panel.form.get('entries') as FormArray).length).toBe(2);
            });
        }

        it('treats a write value left at the variables. prefill, or cleared, as empty', () => {
            const { panel, fixture } = createPanel(nodes.write, { renderTemplate: true });
            const added = addEntry(fixture, panel);

            expect(added.value).toEqual({ key: '', value: 'variables.' });
            expect(panel.form.valid).toBe(true);

            added.patchValue({ value: '  ' });
            expect(panel.form.valid).toBe(true);
            expect(panel.onSave()!.data.entries).toEqual([{ key: 'plan', value: 'variables.plan' }]);
        });

        it('still validates a write row that has only a value typed', () => {
            const { panel, fixture } = createPanel(nodes.write, { renderTemplate: true });
            const added = addEntry(fixture, panel);

            added.patchValue({ value: 'variables.user' });

            expect(added.get('key')!.hasError('required')).toBe(true);
            expect(panel.onSave()).toBeNull();

            // Back to the prefill: empty again.
            added.patchValue({ value: 'variables.' });
            expect(panel.form.valid).toBe(true);
        });

        it('still validates a read row that has only an alias or only a default typed', () => {
            const { panel, fixture } = createPanel(nodes.read, { renderTemplate: true });
            const added = addEntry(fixture, panel);

            added.patchValue({ alias: 'user' });
            expect(added.get('key')!.hasError('required')).toBe(true);
            expect(panel.onSave()).toBeNull();

            added.patchValue({ alias: '', default: '"free"' });
            expect(added.get('key')!.hasError('required')).toBe(true);
            expect(added.get('alias')!.hasError('required')).toBe(true);
            expect(panel.onSave()).toBeNull();
        });

        it('validates the rest of the row once a key is typed', () => {
            const { panel, fixture } = createPanel(nodes.write, { renderTemplate: true });
            const added = addEntry(fixture, panel);

            added.patchValue({ key: 'profile' });

            expect(added.get('value')!.hasError('pattern')).toBe(true);
            expect(panel.onSave()).toBeNull();
        });

        it('leaves empty rows out of the canvas key count', () => {
            vi.useFakeTimers();
            const { panel, fixture, triggerAutosave } = createPanel(nodes.delete, { renderTemplate: true });
            const added = addEntry(fixture, panel);

            vi.advanceTimersByTime(300);
            expect(triggerAutosave).not.toHaveBeenCalled();

            added.patchValue({ key: 'profile' });
            vi.advanceTimersByTime(300);
            expect(triggerAutosave).toHaveBeenCalledTimes(1);
            expect(panel.onSave()!.data.entries).toEqual([{ key: 'plan' }, { key: 'profile' }]);
        });
    });

    describe('key suggestions', () => {
        const page = (keys: string[]): ApiGetRequest<PersistenceTableEntry> => ({
            count: keys.length,
            next: null,
            previous: null,
            results: keys.map((key) => ({ key }) as PersistenceTableEntry),
        });
        const typeKey = (fixture: ComponentFixture<PersistenceNodePanelComponent>, text: string): HTMLInputElement => {
            const input: HTMLInputElement = fixture.nativeElement.querySelector('input[aria-label="Key"]');
            input.value = text;
            input.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(250);
            fixture.detectChanges();
            return input;
        };
        const suggestionItems = (): HTMLElement[] => Array.from(document.querySelectorAll<HTMLElement>('.vdo-item'));
        const firstKey = (panel: PersistenceNodePanelComponent): string =>
            (panel.form.get('entries') as FormArray).at(0).get('key')!.value;

        beforeEach(() => vi.useFakeTimers());

        it('searches the selected table and fills the key with the clicked suggestion', () => {
            const getEntries = vi.fn(() => of(page(['greeting', 'greeting_formal'])));
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                canRead: true,
                getEntries,
            });

            typeKey(fixture, 'gre');

            expect(getEntries).toHaveBeenCalledWith({ table: 3, search: 'gre', limit: 20, offset: 0 });
            expect(suggestionItems().map((item) => item.textContent!.trim())).toEqual(['greeting', 'greeting_formal']);

            suggestionItems()[1].click();
            fixture.detectChanges();

            expect(firstKey(panel)).toBe('greeting_formal');
            expect(suggestionItems()).toEqual([]);
        });

        it('marks the key input as a combobox that is expanded while the list is open', () => {
            const { fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                canRead: true,
                getEntries: () => of(page(['greeting'])),
            });
            const input: HTMLInputElement = fixture.nativeElement.querySelector('input[aria-label="Key"]');
            expect(input.getAttribute('role')).toBe('combobox');
            expect(input.getAttribute('aria-expanded')).toBe('false');

            typeKey(fixture, 'gre');
            expect(input.getAttribute('aria-expanded')).toBe('true');
        });

        it('picks the hovered suggestion on Enter', () => {
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                canRead: true,
                getEntries: () => of(page(['greeting', 'greeting_formal', 'greeting_short'])),
            });

            const input = typeKey(fixture, 'gre');
            suggestionItems()[2].dispatchEvent(new MouseEvent('mouseenter'));
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
            fixture.detectChanges();

            expect(firstKey(panel)).toBe('greeting_short');
        });

        it('keeps Escape on an open list from reaching the window shortcut listener', () => {
            const { fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                canRead: true,
                getEntries: () => of(page(['greeting'])),
            });
            const windowKeydown = vi.fn();
            window.addEventListener('keydown', windowKeydown);

            try {
                const input = typeKey(fixture, 'gre');
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
                fixture.detectChanges();

                expect(windowKeydown).not.toHaveBeenCalled();
                expect(suggestionItems()).toEqual([]);

                // With the list closed, Escape goes on to the panel as before.
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
                expect(windowKeydown).toHaveBeenCalledTimes(1);
            } finally {
                window.removeEventListener('keydown', windowKeydown);
            }
        });

        it('drops a response that arrives after a pick, Escape or blur', () => {
            const responses = new Subject<ApiGetRequest<PersistenceTableEntry>>();
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                canRead: true,
                getEntries: () => responses,
            });
            const respond = (): void => {
                responses.next(page(['greeting', 'greeting_formal']));
                fixture.detectChanges();
            };

            typeKey(fixture, 'gre');
            respond();
            suggestionItems()[1].click();
            respond();
            expect(firstKey(panel)).toBe('greeting_formal');
            expect(suggestionItems()).toEqual([]);

            let input = typeKey(fixture, 'greet');
            respond();
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
            respond();
            expect(suggestionItems()).toEqual([]);

            input = typeKey(fixture, 'greeti');
            input.dispatchEvent(new FocusEvent('blur'));
            respond();
            expect(suggestionItems()).toEqual([]);
        });

        it('picks with the arrow keys and Enter, and closes on Escape', () => {
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                canRead: true,
                getEntries: () => of(page(['greeting', 'greeting_formal'])),
            });
            const press = (input: HTMLInputElement, key: string): void => {
                input.dispatchEvent(new KeyboardEvent('keydown', { key }));
                fixture.detectChanges();
            };

            let input = typeKey(fixture, 'gre');
            press(input, 'Escape');
            expect(suggestionItems()).toEqual([]);

            input = typeKey(fixture, 'gree');
            press(input, 'ArrowDown');
            press(input, 'Enter');
            expect(firstKey(panel)).toBe('greeting_formal');
            expect(suggestionItems()).toEqual([]);
        });

        it('does not search a key built from placeholders', () => {
            const getEntries = vi.fn(() => of(page(['profile_1'])));
            const { fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                canRead: true,
                getEntries,
            });

            typeKey(fixture, 'profile_{');

            expect(getEntries).not.toHaveBeenCalled();
            expect(suggestionItems()).toEqual([]);
        });
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

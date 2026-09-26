import { NgTemplateOutlet } from '@angular/common';
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
import {
    PersistenceEntryLookupResponse,
    PersistenceTableEntry,
} from '../../../../features/persistent-data/models/persistence-table.model';
import { PersistenceTablesApiService } from '../../../../features/persistent-data/services/persistence-tables-api.service';
import { PersistenceTablesStorageService } from '../../../../features/persistent-data/services/persistence-tables-storage.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { hasValidPersistenceEntries } from '../../../core/helpers/persistence-node.helpers';
import { FlowModel } from '../../../core/models/flow.model';
import { NodeModel, PersistenceNodeModel } from '../../../core/models/node.model';
import {
    GetPersistenceNodeRequest,
    PersistenceEntry,
    PersistenceMode,
} from '../../../core/models/persistence-node.model';
import { FlowService } from '../../../services/flow.service';
import { PersistenceValueDraftsService } from '../../../services/persistence-value-drafts.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { UniqueNodeNameValidatorService } from '../../../services/unique-node-name.validator';
import { mapPersistenceNodeToModel } from '../../../utils/load/nodes/persistence-node.mapper';
import { getNodeDiff } from '../../../utils/save/diff';
import { NodePanelShellComponent } from '../node-panel-shell/node-panel-shell.component';
import { PersistenceNodePanelComponent } from './persistence-node-panel.component';

const DTO: GetPersistenceNodeRequest = {
    id: 12,
    graph: 1,
    node_name: 'Persistence #1',
    persistence_table: 3,
    mode: 'read',
    entries: [
        { key: 'profile', value: 'variables.user' },
        { key: 'plan', value: 'variables.plan' },
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

function nodeWith(mode: PersistenceMode, entries: PersistenceEntry[]): PersistenceNodeModel {
    return mapPersistenceNodeToModel({ ...DTO, mode, entries });
}

function entriesOf(panel: PersistenceNodePanelComponent): FormArray {
    return panel.form.get('entries') as FormArray;
}

function hintsOf(fixture: ComponentFixture<PersistenceNodePanelComponent>): string[] {
    return Array.from(fixture.nativeElement.querySelectorAll('.entry-hint'), (hint: Element) =>
        hint.textContent!.trim()
    );
}

function openPanel(node: PersistenceNodeModel): ComponentFixture<PersistenceNodePanelComponent> {
    const fixture = TestBed.createComponent(PersistenceNodePanelComponent);
    fixture.componentRef.setInput('node', node);
    fixture.detectChanges();
    return fixture;
}

function createPanel(
    node: PersistenceNodeModel,
    {
        renderTemplate = false,
        canRead = false,
        getEntries = () => NEVER,
        lookupEntries = () => of({}),
        initialState = {},
        errorOnUnknownProperties = true,
    }: {
        renderTemplate?: boolean;
        canRead?: boolean;
        getEntries?: () => Observable<ApiGetRequest<PersistenceTableEntry>>;
        lookupEntries?: () => Observable<PersistenceEntryLookupResponse>;
        initialState?: Record<string, unknown>;
        errorOnUnknownProperties?: boolean;
    } = {}
): {
    panel: PersistenceNodePanelComponent;
    fixture: ComponentFixture<PersistenceNodePanelComponent>;
    triggerAutosave: ReturnType<typeof vi.fn>;
    toastError: ReturnType<typeof vi.fn>;
} {
    const triggerAutosave = vi.fn();
    const toastError = vi.fn();
    TestBed.configureTestingModule({
        errorOnUnknownProperties,
        providers: [
            {
                provide: PersistenceTablesApiService,
                useValue: { lookupEntries, getEntries },
            },
            { provide: PersistenceTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
            { provide: PermissionsService, useValue: { can: () => canRead } },
            {
                provide: UniqueNodeNameValidatorService,
                useValue: { createSyncUniqueNameValidator: () => () => null, getValidationErrorMessage: () => '' },
            },
            {
                provide: SidePanelService,
                // The shell's side of it too, for the Ctrl+S spec.
                useValue: {
                    triggerAutosave,
                    autosaveTrigger: signal(0),
                    expandRequest: signal(false),
                    clearExpandRequest: vi.fn(),
                    clearSelection: vi.fn(),
                },
            },
            { provide: ToastService, useValue: { error: toastError } },
            { provide: FlowService, useValue: { startNodeInitialState: signal(initialState) } },
            // FlowGraphComponent provides it in the app, so it outlives any one panel.
            PersistenceValueDraftsService,
        ],
    });
    TestBed.overrideComponent(PersistenceNodePanelComponent, {
        set: renderTemplate
            ? {
                  imports: [ReactiveFormsModule, NgTemplateOutlet, FormControlStubComponent],
                  schemas: [CUSTOM_ELEMENTS_SCHEMA],
              }
            : { template: '', imports: [] },
    });
    const fixture = openPanel(node);
    return { panel: fixture.componentInstance, fixture, triggerAutosave, toastError };
}

function flowOf(node: PersistenceNodeModel): FlowModel {
    return { nodes: [node], connections: [] } as unknown as FlowModel;
}

describe('PersistenceNodePanelComponent', () => {
    afterEach(() => vi.useRealTimers());

    it('does not turn an unchanged read node into an update', () => {
        const loaded = mapPersistenceNodeToModel(DTO);
        const { panel } = createPanel(loaded);

        const saved = panel.onSave();

        expect(saved).not.toBeNull();
        expect(getNodeDiff(flowOf(loaded), flowOf(saved!)).persistenceNodes.toUpdate).toEqual([]);
    });

    it('asks for a debounced autosave when mode or table change, so the canvas badge follows', () => {
        vi.useFakeTimers();
        const { panel, triggerAutosave } = createPanel(
            nodeWith('write', [{ key: 'profile', value: 'variables.user' }])
        );

        panel.form.get('mode')!.setValue('delete');
        expect(triggerAutosave).not.toHaveBeenCalled();
        vi.advanceTimersByTime(300);
        expect(triggerAutosave).toHaveBeenCalledTimes(1);

        panel.form.get('persistence_table')!.setValue(4);
        vi.advanceTimersByTime(300);
        expect(triggerAutosave).toHaveBeenCalledTimes(2);

        // What removeEntry() does.
        entriesOf(panel).removeAt(0);
        vi.advanceTimersByTime(300);
        expect(triggerAutosave).toHaveBeenCalledTimes(3);
    });

    it('does not autosave for edits the canvas does not show', () => {
        vi.useFakeTimers();
        const { panel, triggerAutosave } = createPanel(mapPersistenceNodeToModel(DTO));

        panel.form.get('node_name')!.setValue('Renamed');
        entriesOf(panel).at(0).patchValue({ value: 'variables.other' });
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

    it('has no output variable path field and saves null in every mode', () => {
        const node: PersistenceNodeModel = {
            ...mapPersistenceNodeToModel(DTO),
            output_variable_path: 'variables.saved',
        };
        const { panel, fixture } = createPanel(node, { renderTemplate: true });

        for (const mode of ['read', 'write', 'delete'] as const) {
            panel.form.get('mode')!.setValue(mode);
            fixture.detectChanges();

            expect(fixture.nativeElement.querySelector('app-custom-input[label="Output Variable Path"]')).toBeNull();
            expect(panel.form.get('output_variable_path')).toBeNull();
            expect(panel.onSave()!.output_variable_path).toBeNull();
        }
    });

    it('names the keys section after the mode', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });
        const label = (): string => fixture.nativeElement.querySelector('.entries app-tooltip').label;

        expect(label()).toBe('Keys to Read');
        for (const [mode, text] of [
            ['write', 'Keys to Write'],
            ['delete', 'Keys to Delete'],
        ] as const) {
            panel.form.get('mode')!.setValue(mode);
            fixture.detectChanges();
            expect(label()).toBe(text);
        }
    });

    it('lays read rows out as variable = key, write rows as key = variable, and delete rows as the key alone', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });
        // Each row's fields and the separator between them, in the order they are shown.
        const layout = (): string[] =>
            Array.from(
                (fixture.nativeElement.querySelector('.entry-row') as HTMLElement).querySelectorAll(
                    'input, .equals-sign, .remove-entry'
                ),
                (element) => element.getAttribute('aria-label') ?? element.getAttribute('title') ?? element.textContent!
            );

        expect(layout()).toEqual(['Variable path', '=', 'Key', 'Remove']);

        panel.form.get('mode')!.setValue('write');
        fixture.detectChanges();
        expect(layout()).toEqual(['Key', '=', 'Variable path', 'Remove']);

        panel.form.get('mode')!.setValue('delete');
        fixture.detectChanges();
        expect(layout()).toEqual(['Key', 'Remove']);
    });

    it("separates the fields with the Input List's = sign", () => {
        const { fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });
        const separators: HTMLElement[] = Array.from(
            fixture.nativeElement.querySelectorAll('.entry-row > .equals-sign')
        );

        expect(separators.map((separator) => [separator.tagName, separator.className, separator.textContent])).toEqual([
            ['DIV', 'equals-sign', '='],
            ['DIV', 'equals-sign', '='],
        ]);
    });

    it('keeps each hint under its own field whichever side it is on', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });

        entriesOf(panel).at(0).patchValue({ key: 'p_{user_id}', value: 'user.name' });
        fixture.detectChanges();
        const fields: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('.entry-row')[0].children);
        const hintsUnder = (label: string): string[] => {
            const field = fields.find((element) => element.querySelector(`input[aria-label="${label}"]`))!;
            return Array.from(field.querySelectorAll('.entry-hint'), (hint) => hint.textContent!.trim());
        };

        expect(hintsUnder('Variable path')).toEqual(['Use variables.user.name']);
        expect(hintsUnder('Key')).toEqual(['Use {variables.user_id}']);
    });

    it('accepts only state paths as read and write values, with a default only for write', () => {
        const invalidPaths = [
            'name',
            'variables',
            'variables.',
            'variables[0]',
            '   ',
            'variables.user-name',
            'variables.a b',
            'variables._private',
            'variables.user.__class__',
            'variables.user-name|0',
        ];
        const validPaths: Record<'read' | 'write', string[]> = {
            read: ['variables.a.b', 'variables.items[0].name', ' variables.a ', 'variables.a_b'],
            write: ['variables.a.b', 'variables.x|0', 'variables.x|', 'variables.items[0]', ' variables.a '],
        };
        for (const mode of ['read', 'write'] as const) {
            const { panel } = createPanel(nodeWith(mode, [{ key: 'profile', value: '' }]));
            const value = entriesOf(panel).at(0).get('value')!;

            for (const path of validPaths[mode]) {
                value.setValue(path);
                expect(value.valid).toBe(true);
            }
            for (const path of mode === 'read' ? [...invalidPaths, 'variables.x|0'] : invalidPaths) {
                value.setValue(path);
                expect(value.hasError('pattern')).toBe(true);
            }
            value.setValue('');
            expect(value.hasError('required')).toBe(true);
            TestBed.resetTestingModule();
        }
    });

    it('says how to fix a value that is not a state path, and saves it trimmed', () => {
        const { panel, fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.a' }]), {
            renderTemplate: true,
        });
        const value = entriesOf(panel).at(0).get('value')!;

        value.setValue('user.name');
        fixture.detectChanges();
        expect(hintsOf(fixture)).toEqual(['Use variables.user.name']);

        value.setValue('user name');
        fixture.detectChanges();
        expect(hintsOf(fixture)).toEqual(['Use a state path like variables.user.name']);

        value.setValue('variables.user-name|0');
        fixture.detectChanges();
        expect(hintsOf(fixture)).toEqual(['Use letters, digits and _ in variable names, like variables.user_name']);

        value.setValue('variables._secret');
        fixture.detectChanges();
        expect(hintsOf(fixture)).toEqual(["Variable names can't start with _"]);

        value.setValue('  variables.user.name ');
        fixture.detectChanges();
        expect(hintsOf(fixture)).toEqual([]);
        expect(panel.onSave()!.data.entries).toEqual([{ key: 'profile', value: 'variables.user.name' }]);
    });

    it('says a read value takes no default', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });

        entriesOf(panel).at(0).patchValue({ value: 'variables.user|0' });
        fixture.detectChanges();

        expect(hintsOf(fixture)).toEqual(['Leave out the |default: a missing key reads None']);
    });

    it('says how to write key placeholders, building the fix from what was typed', () => {
        const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });
        const entries = entriesOf(panel);

        entries.at(0).patchValue({ key: 'profile_{user_id}' });
        entries.at(1).patchValue({ key: 'plan_{ variables.user.id }' });
        fixture.detectChanges();

        expect(hintsOf(fixture)).toEqual(['Use {variables.user_id}']);

        entries.at(1).patchValue({ key: 'plan_{}' });
        fixture.detectChanges();

        expect(hintsOf(fixture)).toEqual(['Use {variables.user_id}', 'Write placeholders as {variables.user.id}']);
    });

    for (const mode of ['read', 'write'] as const) {
        it(`prefills the value of a new ${mode} entry and shows its hint only once touched`, () => {
            const { panel, fixture } = createPanel(nodeWith(mode, [{ key: 'profile', value: 'variables.a' }]), {
                renderTemplate: true,
            });

            fixture.nativeElement.querySelector('.add-entry').click();
            fixture.detectChanges();

            const added = entriesOf(panel).at(1);
            expect(added.value).toEqual({ key: '', value: 'variables.' });
            expect(panel.form.valid).toBe(true);
            // A key makes the row count, so its prefilled value is now checked.
            added.patchValue({ key: 'plan' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([]);

            added.get('value')!.markAsTouched();
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual(['Use a state path like variables.user.name']);
        });
    }

    it('says whether a static key is stored as a plain hint, and nothing for a key built at run time', () => {
        vi.useFakeTimers();
        const lookupEntries = vi.fn(() => of({ plan: { exists: false, value_preview: null, updated_at: null } }));
        const { fixture } = createPanel(
            nodeWith('write', [
                { key: 'plan', value: 'variables.plan' },
                { key: 'profile_{variables.user.id}', value: 'variables.user' },
            ]),
            { renderTemplate: true, canRead: true, lookupEntries }
        );

        vi.advanceTimersByTime(300);
        fixture.detectChanges();

        expect(lookupEntries).toHaveBeenCalledWith(3, ['plan']);
        expect(hintsOf(fixture)).toEqual(['New key']);
        expect(fixture.nativeElement.querySelector('.badge')).toBeNull();
    });

    it('says a stored read key exists and a missing one reads None', () => {
        vi.useFakeTimers();
        const lookupEntries = vi.fn(() =>
            of({
                profile: { exists: true, value_preview: '"x"', updated_at: '2026-09-23T10:00:00Z' },
                plan: { exists: false, value_preview: null, updated_at: null },
            })
        );
        const { fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
            renderTemplate: true,
            canRead: true,
            lookupEntries,
        });

        vi.advanceTimersByTime(300);
        fixture.detectChanges();

        expect(hintsOf(fixture)).toEqual(['Exists', 'New key — reads None']);
    });

    describe('mode switching', () => {
        it('keeps keys and values when switching between read and write', () => {
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), { renderTemplate: true });

            panel.form.get('mode')!.setValue('write');
            fixture.detectChanges();
            expect(entriesOf(panel).getRawValue()).toEqual(DTO.entries);

            panel.form.get('mode')!.setValue('read');
            expect(entriesOf(panel).getRawValue()).toEqual(DTO.entries);
        });

        // Regression: rows sharing a key, including rows with no key typed yet, all came back with the
        // last such row's value, because drafts were remembered per key text.
        it('gives each row its own value back after write -> delete -> write, as typed in the panel', () => {
            const { panel, fixture } = createPanel(nodeWith('write', []), { renderTemplate: true });
            const type = (label: string, row: number, text: string): void => {
                const input: HTMLInputElement = fixture.nativeElement.querySelectorAll(`input[aria-label="${label}"]`)[
                    row
                ];
                input.value = text;
                input.dispatchEvent(new Event('input'));
                fixture.detectChanges();
            };
            const switchTo = (mode: PersistenceMode): void => {
                panel.form.get('mode')!.setValue(mode);
                fixture.detectChanges();
            };
            const rows: [string, string][] = [
                ['test1', 'variables.my_key1'],
                ['test2', 'variables.my_key2'],
            ];
            rows.forEach(([key, value], row) => {
                fixture.nativeElement.querySelector('.add-entry').click();
                fixture.detectChanges();
                type('Key', row, key);
                type('Variable path', row, value);
            });
            const typed = rows.map(([key, value]) => ({ key, value }));

            switchTo('delete');
            switchTo('write');
            expect(entriesOf(panel).getRawValue()).toEqual(typed);

            // Values typed before the keys: both rows share the empty key when the mode switches.
            entriesOf(panel).controls.forEach((row) => row.patchValue({ key: '' }));
            switchTo('delete');
            switchTo('write');
            expect(entriesOf(panel).getRawValue()).toEqual(typed.map(({ value }) => ({ key: '', value })));
        });

        it('gives rows sharing a key their own values back on every round trip, also after reopening', () => {
            const entries: PersistenceEntry[] = [
                { key: 'profile', value: 'variables.first' },
                { key: 'plan', value: 'variables.plan' },
                { key: 'profile', value: 'variables.second' },
            ];
            const { panel, fixture } = createPanel(nodeWith('read', entries));
            const switchTo = (form: PersistenceNodePanelComponent, mode: PersistenceMode): void =>
                form.form.get('mode')!.setValue(mode);

            for (const [via, back] of [
                ['delete', 'read'],
                ['write', 'delete'],
                ['delete', 'write'],
                ['read', 'delete'],
                ['delete', 'read'],
            ] as const) {
                switchTo(panel, via);
                switchTo(panel, back);
                if (back !== 'delete') expect(entriesOf(panel).getRawValue()).toEqual(entries);
            }

            switchTo(panel, 'delete');
            const closed = panel.onSave()!;
            fixture.destroy();
            const reopened = openPanel(closed).componentInstance;
            switchTo(reopened, 'write');

            expect(entriesOf(reopened).getRawValue()).toEqual(entries);
        });

        it('gives a row its own value back after the row above it with the same key is removed in delete mode', () => {
            const { panel, fixture } = createPanel(
                nodeWith('write', [
                    { key: 'profile', value: 'variables.first' },
                    { key: 'profile', value: 'variables.second' },
                ])
            );

            panel.form.get('mode')!.setValue('delete');
            entriesOf(panel).removeAt(0);
            panel.form.get('mode')!.setValue('write');
            expect(entriesOf(panel).getRawValue()).toEqual([{ key: 'profile', value: 'variables.second' }]);

            // Also once the panel is closed in delete mode and opened again.
            panel.form.get('mode')!.setValue('delete');
            const closed = panel.onSave()!;
            fixture.destroy();
            const reopened = openPanel(closed).componentInstance;
            reopened.form.get('mode')!.setValue('write');

            expect(entriesOf(reopened).getRawValue()).toEqual([{ key: 'profile', value: 'variables.second' }]);
        });

        it('gives rows with no key yet their own values back after a key is typed in delete mode', () => {
            const { panel, fixture } = createPanel(nodeWith('write', []), { renderTemplate: true });
            for (const value of ['variables.v1', 'variables.v2']) {
                fixture.nativeElement.querySelector('.add-entry').click();
                entriesOf(panel)
                    .at(entriesOf(panel).length - 1)
                    .patchValue({ value });
            }

            panel.form.get('mode')!.setValue('delete');
            entriesOf(panel).at(0).patchValue({ key: 'a' });
            panel.form.get('mode')!.setValue('write');

            expect(entriesOf(panel).getRawValue()).toEqual([
                { key: 'a', value: 'variables.v1' },
                { key: '', value: 'variables.v2' },
            ]);
        });

        it('restores the values after a switch to delete and back', () => {
            const { panel } = createPanel(mapPersistenceNodeToModel(DTO));

            panel.form.get('mode')!.setValue('delete');
            expect(entriesOf(panel).getRawValue()).toEqual([{ key: 'profile' }, { key: 'plan' }]);
            entriesOf(panel).at(1).patchValue({ key: 'tier' });

            panel.form.get('mode')!.setValue('write');
            expect(entriesOf(panel).getRawValue()).toEqual([
                { key: 'profile', value: 'variables.user' },
                // A row keeps its value when its key is renamed in delete mode.
                { key: 'tier', value: 'variables.plan' },
            ]);
            // Saves only what the current mode has.
            expect(panel.onSave()!.data.entries).toEqual([
                { key: 'profile', value: 'variables.user' },
                { key: 'tier', value: 'variables.plan' },
            ]);
        });

        it('restores the values after the panel is closed in delete mode and reopened', () => {
            const { panel, fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.user' }]));

            panel.form.get('mode')!.setValue('delete');
            // What closing the panel puts into the flow.
            const closed = panel.onSave()!;
            expect(closed.data).toEqual({ persistence_table: 3, mode: 'delete', entries: [{ key: 'profile' }] });
            fixture.destroy();

            const reopened = openPanel(closed).componentInstance;
            reopened.form.get('mode')!.setValue('write');

            expect(entriesOf(reopened).getRawValue()).toEqual([{ key: 'profile', value: 'variables.user' }]);
        });

        it('does not restore values into another node', () => {
            const { panel, fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.user' }]));
            panel.form.get('mode')!.setValue('delete');
            fixture.destroy();

            const other = openPanel({
                ...nodeWith('delete', [{ key: 'profile' }]),
                id: 'other-node',
            }).componentInstance;
            other.form.get('mode')!.setValue('write');

            expect(entriesOf(other).getRawValue()).toEqual([{ key: 'profile', value: 'variables.' }]);
        });

        // Regression: the canvas kept the old mode forever, because the switch leaves entries invalid
        // and autosave and panel close both dropped an invalid node.
        it('puts the new mode on the canvas even when the switch leaves entries invalid, which the flow save refuses', () => {
            vi.useFakeTimers();
            const { panel, triggerAutosave, toastError } = createPanel(
                nodeWith('delete', [{ key: 'profile_{variables.user.id}' }])
            );

            panel.form.get('mode')!.setValue('write');
            vi.advanceTimersByTime(300);
            expect(triggerAutosave).toHaveBeenCalledTimes(1);
            expect(panel.form.valid).toBe(false);

            // What the panel shell writes to the flow on autosave and on close.
            const synced = panel.onSave();
            expect(synced!.data).toEqual({
                persistence_table: 3,
                mode: 'write',
                entries: [{ key: 'profile_{variables.user.id}', value: 'variables.' }],
            });
            expect(hasValidPersistenceEntries(synced!.data)).toBe(false);
            // Ctrl+S and the flow save still refuse the invalid entries.
            expect(panel.onSaveSilently()).toBeNull();
            expect(panel.captureForValidation()).toBeNull();
            expect(toastError).toHaveBeenCalledTimes(1);
        });

        it('stays open on Ctrl+S outside a text input while entries are invalid', () => {
            vi.useFakeTimers();
            // The shell hands every panel a graphId input, which this panel does not declare.
            const { fixture: panelFixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'value' }]), {
                errorOnUnknownProperties: false,
            });
            panelFixture.destroy();
            const shellFixture = TestBed.createComponent(NodePanelShellComponent);
            const saved = vi.fn();
            shellFixture.componentInstance.save.subscribe(saved);
            shellFixture.componentRef.setInput('node', nodeWith('write', [{ key: 'profile', value: 'value' }]));
            shellFixture.detectChanges();
            // The shell picks up the panel it rendered on the next tick.
            vi.advanceTimersByTime(0);
            const pressCtrlS = (): void => {
                document.body.dispatchEvent(
                    new KeyboardEvent('keydown', { key: 's', code: 'KeyS', ctrlKey: true, bubbles: true })
                );
            };

            pressCtrlS();
            expect(saved).not.toHaveBeenCalled();

            const panel: PersistenceNodePanelComponent = shellFixture.debugElement.query(
                (element) => element.componentInstance instanceof PersistenceNodePanelComponent
            ).componentInstance;
            entriesOf(panel).at(0).patchValue({ value: 'variables.user' });
            pressCtrlS();
            expect(saved).toHaveBeenCalledTimes(1);
            expect((saved.mock.calls[0][0] as NodeModel).id).toBe(panel.node().id);
        });

        it('still holds back an invalid node name', () => {
            const { panel } = createPanel(mapPersistenceNodeToModel(DTO));

            panel.form.get('node_name')!.setValue('');

            expect(panel.onSave()).toBeNull();
            expect(panel.onSaveSilently()).toBeNull();
        });
    });

    describe('flow save', () => {
        const writeNode = (value: string): PersistenceNodeModel => nodeWith('write', [{ key: 'profile', value }]);

        it('blocks the flow save and says why when a write value is not a state path', () => {
            const { panel, toastError } = createPanel(writeNode('value'));

            expect(panel.captureForValidation()).toBeNull();
            expect(toastError).toHaveBeenCalledWith('Fix the highlighted fields in "Persistence #1" to save the flow.');
            // Touched, so the invalid field renders its error.
            expect(entriesOf(panel).at(0).get('value')!.touched).toBe(true);
        });

        it('passes a valid node through', () => {
            const { panel, toastError } = createPanel(writeNode('variables.user'));

            expect(panel.captureForValidation()!.data.entries).toEqual([{ key: 'profile', value: 'variables.user' }]);
            expect(toastError).not.toHaveBeenCalled();
        });

        it('is not blocked by an empty row', () => {
            const { panel, fixture, toastError } = createPanel(writeNode('variables.user'), { renderTemplate: true });

            fixture.nativeElement.querySelector('.add-entry').click();
            fixture.detectChanges();

            expect(panel.captureForValidation()!.data.entries).toEqual([{ key: 'profile', value: 'variables.user' }]);
            expect(toastError).not.toHaveBeenCalled();
        });
    });

    describe('entry validation', () => {
        it('blocks the flow save when a key is typed but the value is left at the prefill, hinting once touched', () => {
            const { panel, fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.a' }]), {
                renderTemplate: true,
            });
            fixture.nativeElement.querySelector('.add-entry').click();
            entriesOf(panel).at(1).patchValue({ key: 'plan' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([]);

            expect(panel.captureForValidation()).toBeNull();
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual(['Use a state path like variables.user.name']);
        });

        it('blocks the flow save for a malformed key or a placeholder that is not a state path', () => {
            const { panel } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.a' }]));
            const key = entriesOf(panel).at(0).get('key')!;

            for (const template of ['p_{', 'p_{}', 'p_{user_id}', 'p_{variables[0]}']) {
                key.setValue(template);
                expect(key.hasError('keyTemplate')).toBe(true);
                expect(panel.captureForValidation()).toBeNull();
            }
            key.setValue('p_{ variables.user.id }');
            expect(panel.captureForValidation()).not.toBeNull();
        });

        it('blocks the flow save for a key of only spaces', () => {
            const { panel } = createPanel(mapPersistenceNodeToModel(DTO));
            const row = entriesOf(panel).at(0);

            row.patchValue({ key: '   ' });
            expect(row.get('key')!.hasError('required')).toBe(true);
            expect(panel.captureForValidation()).toBeNull();
        });

        it('blocks the flow save when two write rows share a key, marking both until one changes', () => {
            const { panel, fixture } = createPanel(
                nodeWith('write', [
                    { key: 'profile', value: 'variables.user' },
                    { key: 'plan', value: 'variables.plan' },
                ]),
                { renderTemplate: true }
            );
            const entries = entriesOf(panel);
            const redInputs = (): string[] =>
                Array.from(
                    fixture.nativeElement.querySelectorAll('.entry-input.duplicate'),
                    (input: Element) => input.getAttribute('aria-label')!
                );

            // Compared trimmed.
            entries.at(1).patchValue({ key: ' profile ' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([
                'Duplicate key — use a different key',
                'Duplicate key — use a different key',
            ]);
            expect(redInputs()).toEqual(['Key', 'Key']);
            expect(entries.at(0).get('key')!.hasError('duplicateKey')).toBe(true);
            expect(panel.captureForValidation()).toBeNull();

            // Fixing one row clears the other, which did not change.
            entries.at(1).patchValue({ key: 'plan' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([]);
            expect(redInputs()).toEqual([]);
            expect(panel.captureForValidation()).not.toBeNull();
        });

        it('blocks the flow save when two write rows share a variable, whatever their defaults', () => {
            const { panel, fixture } = createPanel(
                nodeWith('write', [
                    { key: 'profile', value: 'variables.user' },
                    { key: 'plan', value: 'variables.plan' },
                ]),
                { renderTemplate: true }
            );
            const entries = entriesOf(panel);

            entries.at(1).patchValue({ value: ' variables.user|{}' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([
                'Duplicate variable — use a different variable',
                'Duplicate variable — use a different variable',
            ]);
            expect(
                Array.from(fixture.nativeElement.querySelectorAll('.entry-input.duplicate'), (input: Element) =>
                    input.getAttribute('aria-label')
                )
            ).toEqual(['Variable path', 'Variable path']);
            expect(panel.captureForValidation()).toBeNull();

            entries.at(1).patchValue({ value: 'variables.plan|0' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([]);
            expect(panel.captureForValidation()).not.toBeNull();
        });

        it('allows repeated keys and variables in read, and repeated keys in delete', () => {
            const repeated: PersistenceEntry[] = [
                { key: 'profile', value: 'variables.same' },
                { key: 'profile', value: 'variables.same' },
            ];
            for (const node of [
                nodeWith('read', repeated),
                nodeWith('delete', [{ key: 'profile' }, { key: 'profile' }]),
            ]) {
                const { panel, fixture } = createPanel(node, { renderTemplate: true });

                expect(panel.form.valid).toBe(true);
                expect(hintsOf(fixture)).toEqual([]);
                TestBed.resetTestingModule();
            }
        });

        it('flags repeats a write node is loaded with', () => {
            const { panel } = createPanel(
                nodeWith('write', [
                    { key: 'a', value: 'variables.same' },
                    { key: 'b', value: 'variables.same' },
                ])
            );

            expect(panel.form.valid).toBe(false);
        });

        it('does not call empty rows, unfinished paths or malformed keys duplicates', () => {
            const { panel, fixture } = createPanel(
                nodeWith('write', [
                    { key: 'profile', value: 'variables.user' },
                    { key: 'plan', value: 'variables.plan' },
                ]),
                { renderTemplate: true }
            );
            const addKey = (): void => {
                fixture.nativeElement.querySelector('.add-entry').click();
                fixture.detectChanges();
            };

            // Two Add key rows, one with a key typed: both still at the variables. prefill.
            addKey();
            addKey();
            entriesOf(panel).at(2).patchValue({ key: 'tier' });
            fixture.detectChanges();
            expect(entriesOf(panel).at(2).get('value')!.hasError('duplicateSource')).toBe(false);
            expect(hintsOf(fixture)).toEqual([]);

            // The same rootless path twice gets the fix, not the duplicate hint; so does a malformed key.
            entriesOf(panel).at(0).patchValue({ key: 'p_{', value: 'user.name' });
            entriesOf(panel).at(1).patchValue({ key: 'p_{', value: 'user.name' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([
                'Write placeholders as {variables.user.id}',
                'Use variables.user.name',
                'Write placeholders as {variables.user.id}',
                'Use variables.user.name',
            ]);
        });

        it('shows no duplicate hint after a switch from delete to write with several keys', () => {
            const { panel, fixture } = createPanel(nodeWith('delete', [{ key: 'a' }, { key: 'b' }, { key: 'c' }]), {
                renderTemplate: true,
            });

            panel.form.get('mode')!.setValue('write');
            fixture.detectChanges();

            expect(entriesOf(panel).controls.some((row) => row.get('value')!.hasError('duplicateSource'))).toBe(false);
            expect(hintsOf(fixture)).toEqual([]);
        });

        it('names the node by its saved name in the toast when the typed name is blank', () => {
            const { panel, toastError } = createPanel(nodeWith('write', [{ key: 'profile', value: 'value' }]));

            for (const name of ['', '   ']) {
                panel.form.get('node_name')!.setValue(name);
                expect(panel.captureForValidation()).toBeNull();
                expect(toastError).toHaveBeenLastCalledWith(
                    'Fix the highlighted fields in "Persistence #1" to save the flow.'
                );
            }
        });
    });

    describe('empty entries', () => {
        const nodes: Record<PersistenceMode, PersistenceNodeModel> = {
            read: nodeWith('read', [{ key: 'plan', value: 'variables.plan' }]),
            write: nodeWith('write', [{ key: 'plan', value: 'variables.plan' }]),
            delete: nodeWith('delete', [{ key: 'plan' }]),
        };
        const addEntry = (
            fixture: ComponentFixture<PersistenceNodePanelComponent>,
            panel: PersistenceNodePanelComponent
        ): AbstractControl => {
            fixture.nativeElement.querySelector('.add-entry').click();
            fixture.detectChanges();
            const entries = entriesOf(panel);
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
                expect(entriesOf(panel).length).toBe(2);
            });
        }

        it('treats a value left at the variables. prefill, or cleared, as empty', () => {
            const { panel, fixture } = createPanel(nodes.write, { renderTemplate: true });
            const added = addEntry(fixture, panel);

            expect(added.value).toEqual({ key: '', value: 'variables.' });
            expect(panel.form.valid).toBe(true);

            added.patchValue({ value: '  ' });
            expect(panel.form.valid).toBe(true);
            expect(panel.onSave()!.data.entries).toEqual([{ key: 'plan', value: 'variables.plan' }]);
        });

        for (const mode of ['read', 'write'] as const) {
            it(`still validates a ${mode} row that has only a value typed`, () => {
                const { panel, fixture } = createPanel(nodes[mode], { renderTemplate: true });
                const added = addEntry(fixture, panel);

                added.patchValue({ value: 'variables.user' });

                expect(added.get('key')!.hasError('required')).toBe(true);
                expect(panel.captureForValidation()).toBeNull();

                // Back to the prefill: empty again.
                added.patchValue({ value: 'variables.' });
                expect(panel.form.valid).toBe(true);
            });
        }

        it('validates the rest of the row once a key is typed', () => {
            const { panel, fixture } = createPanel(nodes.write, { renderTemplate: true });
            const added = addEntry(fixture, panel);

            added.patchValue({ key: 'profile' });

            expect(added.get('value')!.hasError('pattern')).toBe(true);
            expect(panel.captureForValidation()).toBeNull();
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
        const firstKey = (panel: PersistenceNodePanelComponent): string => entriesOf(panel).at(0).get('key')!.value;

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

    describe('panel and flow save agree', () => {
        // Entries as they sit in the flow: no empty rows.
        const cases: [PersistenceMode, PersistenceEntry[]][] = [
            ['delete', [{ key: 'profile_{variables.user.id}' }]],
            ['delete', [{ key: 'p_{user_id}' }]],
            ['delete', [{ key: 'k'.repeat(513) }]],
            ['delete', [{ key: 'p_{variables._id}' }]],
            ['write', [{ key: 'a', value: 'variables.a|0' }]],
            ['write', [{ key: 'a', value: 'variables.' }]],
            ['write', [{ key: 'a', value: 'variables.a-b|0' }]],
            ['write', [{ key: 'a', value: '   ' }]],
            [
                'write',
                [
                    { key: 'a', value: 'variables.same' },
                    { key: 'b', value: 'variables.same' },
                ],
            ],
            [
                'write',
                [
                    { key: 'a', value: 'variables.same' },
                    { key: 'b', value: 'variables.same|0' },
                ],
            ],
            [
                'write',
                [
                    { key: 'a', value: 'variables.x' },
                    { key: ' a ', value: 'variables.y' },
                ],
            ],
            [
                'write',
                [
                    { key: 'a', value: 'variables.x' },
                    { key: 'A', value: 'variables.y|variables.x' },
                ],
            ],
            ['delete', [{ key: 'a' }, { key: 'a' }]],
            [
                'read',
                [
                    { key: 'a', value: 'variables.x' },
                    { key: 'a', value: 'variables.y' },
                ],
            ],
            ['read', [{ key: 'a', value: 'variables.a' }]],
            ['read', [{ key: 'a', value: 'variables.a|0' }]],
            ['read', [{ key: 'a', value: 'variables._a' }]],
            [
                'read',
                [
                    { key: 'a', value: 'variables.x' },
                    { key: 'b', value: ' variables.x ' },
                ],
            ],
            [
                'read',
                [
                    { key: 'a', value: 'user.name' },
                    { key: 'b', value: 'user.name' },
                ],
            ],
        ];

        it('gives the same verdict for every case', () => {
            for (const [mode, entries] of cases) {
                const { panel } = createPanel(nodeWith(mode, entries));
                const panelVerdict = panel.captureForValidation() !== null;
                const flowVerdict = hasValidPersistenceEntries({ persistence_table: 3, mode, entries });

                expect({ mode, entries, verdict: panelVerdict }).toEqual({ mode, entries, verdict: flowVerdict });
                TestBed.resetTestingModule();
            }
        });
    });

    describe('variable picker', () => {
        const initialState = { variables: { user: { id: 1 }, plan: 'free', 'user-name': 'x', _secret: 1 } };
        const valueInput = (fixture: ComponentFixture<PersistenceNodePanelComponent>, row = 0): HTMLInputElement =>
            fixture.nativeElement.querySelectorAll('input[aria-label="Variable path"]')[row];
        const focusValue = (fixture: ComponentFixture<PersistenceNodePanelComponent>, row = 0): HTMLInputElement => {
            const input = valueInput(fixture, row);
            input.dispatchEvent(new FocusEvent('focus'));
            fixture.detectChanges();
            return input;
        };
        const typeValue = (
            fixture: ComponentFixture<PersistenceNodePanelComponent>,
            text: string,
            row = 0
        ): HTMLInputElement => {
            const input = valueInput(fixture, row);
            input.value = text;
            input.dispatchEvent(new Event('input'));
            fixture.detectChanges();
            return input;
        };
        const listed = (): string[] =>
            Array.from(document.querySelectorAll<HTMLElement>('app-var-picker-flat .vpf-item'), (item) => item.title);

        for (const mode of ['read', 'write'] as const) {
            it(`is the Input List's picker under a ${mode} value: opens on focus, filters, fills the clicked path`, () => {
                const { panel, fixture } = createPanel(nodeWith(mode, [{ key: 'profile', value: 'variables.' }]), {
                    renderTemplate: true,
                    initialState,
                });

                const input = focusValue(fixture);
                // Names a persistence node can't use are left out.
                expect(listed()).toEqual(['variables.user', 'variables.user.id', 'variables.plan']);
                // It has no arrow keys or Enter, so the input does not claim to be a combobox.
                expect(input.getAttribute('role')).toBeNull();

                typeValue(fixture, 'variables.US');
                expect(listed()).toEqual(['variables.user', 'variables.user.id']);

                document.querySelectorAll<HTMLElement>('.vpf-item')[1].click();
                fixture.detectChanges();

                expect(entriesOf(panel).at(0).get('value')!.value).toBe('variables.user.id');
                expect(entriesOf(panel).at(0).get('value')!.dirty).toBe(true);
                expect(listed()).toEqual([]);
            });
        }

        it('closes on an exact match, without the variables. prefix, and on Escape, like the Input List', () => {
            const { fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.' }]), {
                renderTemplate: true,
                initialState,
            });

            typeValue(fixture, 'variables.plan');
            expect(listed()).toEqual([]);

            typeValue(fixture, 'variables.pl');
            expect(listed()).toEqual(['variables.plan']);
            typeValue(fixture, 'plan');
            expect(listed()).toEqual([]);

            // The path before a |default is what counts.
            typeValue(fixture, 'variables.plan|free');
            expect(listed()).toEqual([]);
            typeValue(fixture, 'variables.pl|free');
            expect(listed()).toEqual(['variables.plan']);
        });

        it('does not open on focus for a variable with a |default', () => {
            const { fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.plan|0' }]), {
                renderTemplate: true,
                initialState,
            });

            focusValue(fixture);

            expect(document.querySelector('app-var-picker-flat')).toBeNull();
        });

        it('closes on Escape without it reaching the panel, which a second Escape closes', () => {
            const { fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.' }]), {
                renderTemplate: true,
                initialState,
            });
            const windowKeydown = vi.fn();
            window.addEventListener('keydown', windowKeydown);

            try {
                const input = focusValue(fixture);
                expect(listed().length).toBe(3);

                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
                fixture.detectChanges();
                expect(listed()).toEqual([]);
                expect(windowKeydown).not.toHaveBeenCalled();

                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
                expect(windowKeydown).toHaveBeenCalledTimes(1);
            } finally {
                window.removeEventListener('keydown', windowKeydown);
            }
        });

        it('offers every variable in read, where rows may share one', () => {
            const { fixture } = createPanel(
                nodeWith('read', [
                    { key: 'profile', value: 'variables.' },
                    { key: 'plan', value: 'variables.plan' },
                ]),
                { renderTemplate: true, initialState }
            );

            focusValue(fixture);

            expect(listed()).toEqual(['variables.user', 'variables.user.id', 'variables.plan']);
        });

        it('hides the variables other rows use, by their path before any |default', () => {
            const { fixture } = createPanel(
                nodeWith('write', [
                    { key: 'profile', value: 'variables.' },
                    { key: 'plan', value: 'variables.plan|free' },
                ]),
                { renderTemplate: true, initialState }
            );

            focusValue(fixture);

            expect(listed()).toEqual(['variables.user', 'variables.user.id']);
        });

        it('leaves the key input to the stored key suggestions', () => {
            vi.useFakeTimers();
            const { fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.' }]), {
                renderTemplate: true,
                canRead: true,
                getEntries: () =>
                    of({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [{ key: 'profile_1' } as PersistenceTableEntry],
                    }),
                initialState,
            });

            const keyInput: HTMLInputElement = fixture.nativeElement.querySelector('input[aria-label="Key"]');
            keyInput.dispatchEvent(new FocusEvent('focus'));
            keyInput.value = 'pro';
            keyInput.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(250);
            fixture.detectChanges();

            expect(listed()).toEqual([]);
            expect(Array.from(document.querySelectorAll('.vdo-item'), (item) => item.textContent!.trim())).toEqual([
                'profile_1',
            ]);
        });
    });
});

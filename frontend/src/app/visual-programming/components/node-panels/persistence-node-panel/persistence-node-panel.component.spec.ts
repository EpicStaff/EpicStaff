import { Dialog } from '@angular/cdk/dialog';
import { NgTemplateOutlet } from '@angular/common';
import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
    AbstractControl,
    ControlValueAccessor,
    FormArray,
    NG_VALUE_ACCESSOR,
    ReactiveFormsModule,
} from '@angular/forms';
import { SelectDropdownComponent, SelectDropdownTriggerDirective } from '@shared/components';
import { ActionCode, NodeType } from '@shared/models';
import { NEVER, Observable, of, Subject } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { GraphDto } from '../../../../features/flows/models/graph.model';
import {
    PersistenceEntryLookupResponse,
    PersistenceTable,
    PersistenceTableEntryListItem,
} from '../../../../features/persistent-data/models/persistence-table.model';
import { PersistenceTablesApiService } from '../../../../features/persistent-data/services/persistence-tables-api.service';
import { PersistenceTablesStorageService } from '../../../../features/persistent-data/services/persistence-tables-storage.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import {
    hasValidPersistenceEntries,
    invalidPersistenceNodeMessages,
    PERSISTENCE_KEY_MAX_LENGTH,
} from '../../../core/helpers/persistence-node.helpers';
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
import { mapGraphDtoToFlowModel } from '../../../utils/load/map-graph-dto-to-flow-model';
import { mapPersistenceNodeToModel } from '../../../utils/load/nodes/persistence-node.mapper';
import { getNodeDiff } from '../../../utils/save/diff';
import { NodePanelShellComponent } from '../node-panel-shell/node-panel-shell.component';
import { PersistenceNodePanelComponent } from './persistence-node-panel.component';

const ALL_ACTIONS = [ActionCode.Create, ActionCode.Read, ActionCode.Update, ActionCode.Delete];

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
        actions = ALL_ACTIONS,
        tables = [],
        createdTable = NEVER,
        tablesLoad,
        tablesReload,
        getEntries = () => NEVER,
        lookupEntries = () => of({}),
        initialState = {},
        flowService,
        errorOnUnknownProperties = true,
    }: {
        renderTemplate?: boolean;
        /** What the user may do on Key-Value Tables; everything by default. */
        actions?: ActionCode[];
        tables?: PersistenceTable[];
        /** What the create-table dialog closes with. */
        createdTable?: Observable<PersistenceTable | null>;
        /** What the storage's loadTables() and reloadTables() answer; by default the stored tables. */
        tablesLoad?: Observable<PersistenceTable[]>;
        tablesReload?: Observable<PersistenceTable[]>;
        getEntries?: () => Observable<ApiGetRequest<PersistenceTableEntryListItem>>;
        lookupEntries?: () => Observable<PersistenceEntryLookupResponse>;
        initialState?: Record<string, unknown>;
        /** A real one, loaded with a flow; else a stand-in offering initialState. */
        flowService?: FlowService;
        errorOnUnknownProperties?: boolean;
    } = {}
): {
    panel: PersistenceNodePanelComponent;
    fixture: ComponentFixture<PersistenceNodePanelComponent>;
    triggerAutosave: ReturnType<typeof vi.fn>;
    toastError: ReturnType<typeof vi.fn>;
    openDialog: ReturnType<typeof vi.fn>;
    loadTables: ReturnType<typeof vi.fn>;
    reloadTables: ReturnType<typeof vi.fn>;
    storedTables: WritableSignal<PersistenceTable[]>;
    /** What the user may do on Key-Value Tables; set it to change permissions after opening. */
    permittedActions: WritableSignal<ActionCode[]>;
} {
    const triggerAutosave = vi.fn();
    const toastError = vi.fn();
    const openDialog = vi.fn(() => ({ closed: createdTable }));
    const storedTables = signal<PersistenceTable[]>(tables);
    const permittedActions = signal<ActionCode[]>(actions);
    const loadTables = vi.fn(() => tablesLoad ?? of(storedTables()));
    const reloadTables = vi.fn(() => tablesReload ?? of(storedTables()));
    TestBed.configureTestingModule({
        errorOnUnknownProperties,
        providers: [
            {
                provide: PersistenceTablesApiService,
                useValue: { lookupEntries, getEntries },
            },
            { provide: PersistenceTablesStorageService, useValue: { tables: storedTables, loadTables, reloadTables } },
            {
                provide: PermissionsService,
                useValue: {
                    can: (_resource: string, action: ActionCode) => permittedActions().includes(action),
                },
            },
            { provide: Dialog, useValue: { open: openDialog } },
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
            { provide: ToastService, useValue: { error: toastError, success: vi.fn() } },
            { provide: FlowService, useValue: flowService ?? { startNodeInitialState: signal(initialState) } },
            // FlowGraphComponent provides it in the app, so it outlives any one panel.
            PersistenceValueDraftsService,
        ],
    });
    TestBed.overrideComponent(PersistenceNodePanelComponent, {
        set: renderTemplate
            ? {
                  imports: [
                      ReactiveFormsModule,
                      NgTemplateOutlet,
                      FormControlStubComponent,
                      SelectDropdownComponent,
                      SelectDropdownTriggerDirective,
                  ],
                  schemas: [CUSTOM_ELEMENTS_SCHEMA],
              }
            : { template: '', imports: [] },
    });
    const fixture = openPanel(node);
    return {
        panel: fixture.componentInstance,
        fixture,
        triggerAutosave,
        toastError,
        openDialog,
        loadTables,
        reloadTables,
        storedTables,
        permittedActions,
    };
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
            read: ['variables.a.b', 'variables.tags[0].name', ' variables.a ', 'variables.a_b'],
            write: ['variables.a.b', 'variables.x|0', 'variables.x|', 'variables.tags[0]', ' variables.a '],
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

        expect(hintsOf(fixture)).toEqual([
            'Use {variables.user_id}',
            'Close each { with } around a state path, like {variables.user.id}',
        ]);
        expect(entries.at(1).get('key')!.hasError('keyTemplate')).toBe(true);
    });

    it('shows how to write placeholders as the placeholder of an empty key, gone once the key has a value', () => {
        const { panel, fixture } = createPanel(nodeWith('delete', [{ key: '' }]), { renderTemplate: true });
        const keyInput: HTMLInputElement = fixture.nativeElement.querySelector('input[aria-label="Key"]');

        expect(keyInput.placeholder).toBe('Write placeholders as {variables.user.id}');
        expect(keyInput.value).toBe('');

        entriesOf(panel).at(0).patchValue({ key: 'profile_{' });
        fixture.detectChanges();

        // The native placeholder shows only while the input is empty; an unclosed { gets its own hint.
        expect(keyInput.value).toBe('profile_{');
        expect(hintsOf(fixture)).toEqual(['Close each { with } around a state path, like {variables.user.id}']);
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
            { renderTemplate: true, lookupEntries }
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

            entries.at(1).patchValue({ key: 'profile' });
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

        it('lets two write rows with different keys share a variable, whatever their defaults', () => {
            const { panel, fixture } = createPanel(
                nodeWith('write', [
                    { key: 'profile', value: 'variables.user' },
                    { key: 'plan', value: 'variables.plan' },
                ]),
                { renderTemplate: true }
            );

            entriesOf(panel).at(1).patchValue({ value: ' variables.user|{}' });
            fixture.detectChanges();

            expect(hintsOf(fixture)).toEqual([]);
            expect(fixture.nativeElement.querySelectorAll('.entry-input.duplicate').length).toBe(0);
            expect(panel.captureForValidation()).not.toBeNull();
        });

        it('blocks the flow save when two read rows fill one variable, marking both until one changes', () => {
            const { panel, fixture } = createPanel(
                nodeWith('read', [
                    { key: 'key1', value: 'variables.my_var' },
                    { key: 'key2', value: 'variables.other' },
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
            entries.at(1).patchValue({ value: ' variables.my_var ' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([
                'Duplicate variable — use a different variable',
                'Duplicate variable — use a different variable',
            ]);
            expect(redInputs()).toEqual(['Variable path', 'Variable path']);
            expect(entries.at(0).get('value')!.hasError('duplicateVariable')).toBe(true);
            expect(panel.captureForValidation()).toBeNull();

            // Fixing one row clears the other, which did not change.
            entries.at(1).patchValue({ value: 'variables.other' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([]);
            expect(redInputs()).toEqual([]);
            expect(panel.captureForValidation()).not.toBeNull();
        });

        for (const [first, second] of [
            ['variables.user', 'variables.user.name'],
            ['variables.user.name', 'variables.user'],
            ['variables.user', 'variables.user[0]'],
            ['variables.user[0]', 'variables.user'],
        ]) {
            it(`blocks the flow save when read rows fill ${first} and ${second}, one inside the other`, () => {
                const { panel, fixture } = createPanel(
                    nodeWith('read', [
                        { key: 'a', value: first },
                        { key: 'b', value: 'variables.plan' },
                    ]),
                    { renderTemplate: true }
                );

                entriesOf(panel)
                    .at(1)
                    .patchValue({ value: ` ${second} ` });
                fixture.detectChanges();
                expect(hintsOf(fixture)).toEqual([
                    'Overlaps another variable — use a different variable',
                    'Overlaps another variable — use a different variable',
                ]);
                expect(fixture.nativeElement.querySelectorAll('.entry-input.duplicate').length).toBe(2);
                expect(panel.captureForValidation()).toBeNull();

                // Fixing one row clears the other, which did not change.
                entriesOf(panel).at(1).patchValue({ value: 'variables.plan' });
                fixture.detectChanges();
                expect(hintsOf(fixture)).toEqual([]);
                expect(panel.captureForValidation()).not.toBeNull();
            });
        }

        it('lets read rows fill variables whose names only start alike, and write rows share nested sources', () => {
            for (const mode of ['read', 'write'] as const) {
                const { panel, fixture } = createPanel(
                    nodeWith(mode, [
                        { key: 'a', value: 'variables.user' },
                        { key: 'b', value: mode === 'read' ? 'variables.username' : 'variables.user.name' },
                    ]),
                    { renderTemplate: true }
                );

                expect(panel.form.valid).toBe(true);
                expect(hintsOf(fixture)).toEqual([]);
                TestBed.resetTestingModule();
            }
        });

        it('clears the duplicate variable of the row left when the other is removed', () => {
            const { panel, fixture } = createPanel(
                nodeWith('read', [
                    { key: 'a', value: 'variables.my_var' },
                    { key: 'b', value: 'variables.my_var' },
                    { key: 'c', value: 'variables.other' },
                ]),
                { renderTemplate: true }
            );
            expect(entriesOf(panel).at(0).get('value')!.hasError('duplicateVariable')).toBe(true);

            fixture.nativeElement.querySelectorAll('.remove-entry')[1].click();
            fixture.detectChanges();

            expect(entriesOf(panel).at(0).get('value')!.hasError('duplicateVariable')).toBe(false);
            expect(hintsOf(fixture)).toEqual([]);
            expect(panel.form.valid).toBe(true);
        });

        it('flags on both rows two identical read rows a node is loaded with', () => {
            const { panel } = createPanel(
                nodeWith('read', [
                    { key: 'profile', value: 'variables.same' },
                    { key: 'profile', value: 'variables.same' },
                ])
            );

            expect(panel.form.valid).toBe(false);
            expect(entriesOf(panel).controls.map((row) => row.get('value')!.hasError('duplicateVariable'))).toEqual([
                true,
                true,
            ]);
            expect(entriesOf(panel).controls.every((row) => row.get('key')!.valid)).toBe(true);
        });

        it('does not call empty read rows or unfinished paths duplicate variables', () => {
            const { panel, fixture } = createPanel(nodeWith('read', [{ key: 'profile', value: 'variables.user' }]), {
                renderTemplate: true,
            });

            fixture.nativeElement.querySelector('.add-entry').click();
            fixture.nativeElement.querySelector('.add-entry').click();
            entriesOf(panel).at(2).patchValue({ key: 'tier' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([]);

            // The same rootless path twice gets the fix, not the duplicate hint.
            entriesOf(panel).at(0).patchValue({ value: 'user.name' });
            entriesOf(panel).at(2).patchValue({ value: 'user.name' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual(['Use variables.user.name', 'Use variables.user.name']);
        });

        it('checks the rule of the new mode on a switch between read and write', () => {
            const { panel, fixture } = createPanel(
                nodeWith('write', [
                    { key: 'a', value: 'variables.same' },
                    { key: 'b', value: 'variables.same' },
                ]),
                { renderTemplate: true }
            );
            const valueErrors = (): boolean[] =>
                entriesOf(panel).controls.map((row) => row.get('value')!.hasError('duplicateVariable'));
            const keyErrors = (): boolean[] =>
                entriesOf(panel).controls.map((row) => row.get('key')!.hasError('duplicateKey'));

            expect(panel.form.valid).toBe(true);

            panel.form.get('mode')!.setValue('read');
            fixture.detectChanges();
            expect(valueErrors()).toEqual([true, true]);
            expect(hintsOf(fixture)).toEqual([
                'Duplicate variable — use a different variable',
                'Duplicate variable — use a different variable',
            ]);

            // Read rows may share a key, write rows may not.
            entriesOf(panel).at(1).patchValue({ key: 'a', value: 'variables.other' });
            fixture.detectChanges();
            expect(panel.form.valid).toBe(true);

            panel.form.get('mode')!.setValue('write');
            fixture.detectChanges();
            expect(keyErrors()).toEqual([true, true]);
            expect(valueErrors()).toEqual([false, false]);

            // Through delete and back to read: the restored values repeat nothing.
            panel.form.get('mode')!.setValue('delete');
            panel.form.get('mode')!.setValue('read');
            fixture.detectChanges();
            expect(panel.form.valid).toBe(true);
        });

        it('allows a key read into different variables, repeated keys in delete, and repeated variables in write', () => {
            for (const node of [
                nodeWith('read', [
                    { key: 'profile', value: 'variables.a' },
                    { key: 'profile', value: 'variables.b' },
                ]),
                nodeWith('delete', [{ key: 'profile' }, { key: 'profile' }]),
                nodeWith('write', [
                    { key: 'key2', value: 'variables.a' },
                    { key: 'key3', value: 'variables.a' },
                ]),
            ]) {
                const { panel, fixture } = createPanel(node, { renderTemplate: true });

                expect(panel.form.valid).toBe(true);
                expect(hintsOf(fixture)).toEqual([]);
                TestBed.resetTestingModule();
            }
        });

        it('flags on both rows a key a write node is loaded with twice', () => {
            const { panel } = createPanel(
                nodeWith('write', [
                    { key: 'key2', value: 'variables.a' },
                    { key: 'key2', value: 'variables.a' },
                ])
            );

            expect(panel.form.valid).toBe(false);
            expect(entriesOf(panel).controls.map((row) => row.get('key')!.hasError('duplicateKey'))).toEqual([
                true,
                true,
            ]);
            expect(entriesOf(panel).controls.every((row) => row.get('value')!.valid)).toBe(true);
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
            expect(hintsOf(fixture)).toEqual([]);

            // The same rootless path twice gets the fix, not the duplicate hint; so does a malformed key.
            entriesOf(panel).at(0).patchValue({ key: 'p_{', value: 'user.name' });
            entriesOf(panel).at(1).patchValue({ key: 'p_{', value: 'user.name' });
            fixture.detectChanges();
            expect(hintsOf(fixture)).toEqual([
                'Close each { with } around a state path, like {variables.user.id}',
                'Use variables.user.name',
                'Close each { with } around a state path, like {variables.user.id}',
                'Use variables.user.name',
            ]);
        });

        it('shows no duplicate hint after a switch from delete to write with several keys', () => {
            const { panel, fixture } = createPanel(nodeWith('delete', [{ key: 'a' }, { key: 'b' }, { key: 'c' }]), {
                renderTemplate: true,
            });

            panel.form.get('mode')!.setValue('write');
            fixture.detectChanges();

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

    describe('key limit', () => {
        const keys = (count: number): PersistenceEntry[] =>
            Array.from({ length: count }, (_, index) => ({ key: `k${index}` }));
        const addKeyButton = (fixture: ComponentFixture<PersistenceNodePanelComponent>): HTMLButtonElement =>
            fixture.nativeElement.querySelector('.add-entry');

        // Renders 500 rows: about 4s on its own, close to Vitest's 5s default under a full run's load.
        it('stops Add key at 500 rows and says why', { timeout: 20_000 }, () => {
            const { panel, fixture } = createPanel(nodeWith('delete', keys(499)), { renderTemplate: true });

            expect(addKeyButton(fixture).disabled).toBe(false);
            expect(hintsOf(fixture)).toEqual([]);

            addKeyButton(fixture).click();
            fixture.detectChanges();

            expect(entriesOf(panel).length).toBe(500);
            expect(addKeyButton(fixture).disabled).toBe(true);
            expect(hintsOf(fixture)).toEqual(['A Key-Value node can have at most 500 keys']);
            // The empty row is not saved, so 499 keys still save.
            expect(panel.captureForValidation()).not.toBeNull();

            entriesOf(panel).at(499).patchValue({ key: 'k499' });
            expect(panel.captureForValidation()).not.toBeNull();

            fixture.nativeElement.querySelector('.remove-entry').click();
            fixture.detectChanges();
            expect(addKeyButton(fixture).disabled).toBe(false);
            expect(hintsOf(fixture)).toEqual([]);
        });

        it('blocks the flow save for a node loaded with more than 500 keys', () => {
            const { panel } = createPanel(nodeWith('delete', keys(501)));

            expect(entriesOf(panel).hasError('keyLimit')).toBe(true);
            expect(panel.captureForValidation()).toBeNull();
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
        const page = (keys: string[]): ApiGetRequest<PersistenceTableEntryListItem> => ({
            count: keys.length,
            next: null,
            previous: null,
            results: keys.map((key) => ({ key }) as PersistenceTableEntryListItem),
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
            const responses = new Subject<ApiGetRequest<PersistenceTableEntryListItem>>();
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
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
                    { key: 'key2', value: 'variables.a' },
                    { key: 'key2', value: 'variables.a' },
                ],
            ],
            [
                'write',
                [
                    { key: 'key2', value: 'variables.a' },
                    { key: 'key3', value: 'variables.a' },
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
            [
                'read',
                [
                    { key: 'a', value: 'variables.x' },
                    { key: 'a', value: 'variables.x' },
                ],
            ],
            [
                'read',
                [
                    { key: 'key1', value: 'variables.my_var' },
                    { key: 'key2', value: 'variables.my_var' },
                ],
            ],
            [
                'read',
                [
                    { key: 'a', value: 'variables.x|0' },
                    { key: 'b', value: 'variables.x|0' },
                ],
            ],
            [
                'read',
                [
                    { key: 'a', value: 'variables.user' },
                    { key: 'b', value: 'variables.user.name' },
                ],
            ],
            [
                'read',
                [
                    { key: 'a', value: 'variables.user.name' },
                    { key: 'b', value: 'variables.user' },
                ],
            ],
            [
                'read',
                [
                    { key: 'a', value: 'variables.user[0]' },
                    { key: 'b', value: 'variables.user' },
                ],
            ],
            [
                'read',
                [
                    { key: 'a', value: 'variables.user' },
                    { key: 'b', value: 'variables.username' },
                ],
            ],
            ['read', [{ key: 'a', value: 'variables.items' }]],
            ['read', [{ key: 'a', value: 'variables.a[01]' }]],
            ['write', [{ key: 'p_{variables.a[10]}', value: 'variables.a[0]|0' }]],
            ['delete', Array.from({ length: 500 }, (_, index) => ({ key: `k${index}` }))],
            ['delete', Array.from({ length: 501 }, (_, index) => ({ key: `k${index}` }))],
            ['write', [{ key: 'a', value: 'variables.cart.keys|0' }]],
            ['delete', [{ key: 'p_{variables.cart.get}' }]],
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
                expect(input.getAttribute('role')).toBe('combobox');
                expect(input.getAttribute('aria-expanded')).toBe('true');

                typeValue(fixture, 'variables.US');
                expect(listed()).toEqual(['variables.user', 'variables.user.id']);

                document.querySelectorAll<HTMLElement>('.vpf-item')[1].click();
                fixture.detectChanges();

                expect(entriesOf(panel).at(0).get('value')!.value).toBe('variables.user.id');
                expect(entriesOf(panel).at(0).get('value')!.dirty).toBe(true);
                expect(listed()).toEqual([]);
                expect(input.getAttribute('aria-expanded')).toBe('false');
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

        for (const mode of ['read', 'write'] as const) {
            it(`lists an object before its fields in ${mode}, as the Input List does, also when a filter matches only the fields, and only its fields once typed`, () => {
                const { panel, fixture } = createPanel(nodeWith(mode, [{ key: 'profile', value: 'variables.' }]), {
                    renderTemplate: true,
                    initialState: {
                        variables: { my_object: { user_id: 'asdasdasdadadsa', user_email: 'test@mail.com' } },
                    },
                });
                const all = ['variables.my_object', 'variables.my_object.user_id', 'variables.my_object.user_email'];

                focusValue(fixture);
                expect(listed()).toEqual(all);
                typeValue(fixture, 'variables.user');
                expect(listed()).toEqual(all);
                typeValue(fixture, 'variables.my_object.');
                expect(listed()).toEqual(['variables.my_object.user_id', 'variables.my_object.user_email']);

                // The object itself is a valid read target and write source.
                typeValue(fixture, 'variables.');
                document.querySelector<HTMLElement>('.vpf-item')!.click();
                fixture.detectChanges();
                expect(entriesOf(panel).at(0).get('value')!.value).toBe('variables.my_object');
                expect(entriesOf(panel).at(0).get('value')!.valid).toBe(true);
            });
        }

        it('offers every variable in write, also those other rows use, as rows may share one', () => {
            const { fixture } = createPanel(
                nodeWith('write', [
                    { key: 'profile', value: 'variables.' },
                    { key: 'plan', value: 'variables.plan|free' },
                    { key: 'user', value: 'variables.user' },
                ]),
                { renderTemplate: true, initialState }
            );

            focusValue(fixture);

            expect(listed()).toEqual(['variables.user', 'variables.user.id', 'variables.plan']);
            expect(document.querySelectorAll('.vpf-item:disabled').length).toBe(0);
        });

        for (const mode of ['read', 'write'] as const) {
            it(`leaves out in ${mode} the variables named after a DotDict method, which crew can never use`, () => {
                const { fixture } = createPanel(nodeWith(mode, [{ key: 'profile', value: 'variables.' }]), {
                    renderTemplate: true,
                    initialState: { variables: { cart: { items: [1], total: 2 }, keys: 'k', plan: 'free' } },
                });

                focusValue(fixture);

                expect(listed()).toEqual(['variables.cart', 'variables.cart.total', 'variables.plan']);
            });
        }

        it("does not count a read row's own variable as used by another row", () => {
            const { fixture } = createPanel(
                nodeWith('read', [
                    { key: 'profile', value: 'variables.user' },
                    { key: 'plan', value: 'variables.plan' },
                ]),
                { renderTemplate: true, initialState }
            );

            // Its own variable is offered, so it is an exact match and the list stays closed.
            focusValue(fixture);
            expect(listed()).toEqual([]);

            // The input shows only the prefix while the row still holds variables.user.
            valueInput(fixture).value = 'variables.';
            focusValue(fixture);
            expect(listed()).toEqual(['variables.user', 'variables.user.id']);
            expect(document.querySelectorAll('.vpf-item:disabled').length).toBe(0);
        });

        describe('in read, around a variable another row fills', () => {
            const nested = { variables: { user: { id: 1, name: 'n' }, username: 'u', plan: 'free' } };
            const disabled = (): string[] =>
                Array.from(document.querySelectorAll<HTMLElement>('.vpf-item:disabled'), (item) => item.title);

            it('leaves out the object and its fields when another row fills the object', () => {
                const { fixture } = createPanel(
                    nodeWith('read', [
                        { key: 'profile', value: 'variables.' },
                        { key: 'user', value: 'variables.user' },
                    ]),
                    { renderTemplate: true, initialState: nested }
                );

                focusValue(fixture);

                expect(listed()).toEqual(['variables.username', 'variables.plan']);
            });

            it('keeps the object above the other fields as in use when another row fills a field', () => {
                const { fixture } = createPanel(
                    nodeWith('read', [
                        { key: 'profile', value: 'variables.' },
                        { key: 'name', value: ' variables.user.name ' },
                        { key: 'plan', value: 'variables.plan' },
                    ]),
                    { renderTemplate: true, initialState: nested }
                );

                focusValue(fixture);

                expect(listed()).toEqual(['variables.user', 'variables.user.id', 'variables.username']);
                expect(disabled()).toEqual(['variables.user']);
                expect(document.querySelector('.vpf-item:disabled')!.textContent).toContain('in use');
            });

            it('does not take anything away for a target another row has only half typed', () => {
                const { fixture } = createPanel(
                    nodeWith('read', [
                        { key: 'profile', value: 'variables.' },
                        { key: 'user', value: 'variables.user.' },
                    ]),
                    { renderTemplate: true, initialState: nested }
                );

                focusValue(fixture);

                expect(listed()).toEqual([
                    'variables.user',
                    'variables.user.id',
                    'variables.user.name',
                    'variables.username',
                    'variables.plan',
                ]);
                expect(disabled()).toEqual([]);
            });

            it("offers everything around the row's own variable", () => {
                const { fixture } = createPanel(
                    nodeWith('read', [
                        { key: 'name', value: 'variables.user.name' },
                        { key: 'plan', value: 'variables.plan' },
                    ]),
                    { renderTemplate: true, initialState: nested }
                );

                valueInput(fixture).value = 'variables.';
                focusValue(fixture);

                expect(listed()).toEqual([
                    'variables.user',
                    'variables.user.id',
                    'variables.user.name',
                    'variables.username',
                ]);
                expect(disabled()).toEqual([]);
            });
        });

        describe('a flow as the backend returns it, where another write row uses an object', () => {
            const MY_OBJECT = { my_object: { user_id: 'asdasdasdadadsa', user_email: 'test@mail.com' } };
            // The start node's `variables` column holds the whole initial state the Domain Variables
            // dialog saves, flow variables under its own `variables` key.
            const GRAPH = {
                id: 1,
                start_node_list: [
                    { id: 100, graph: 1, node_name: '__start__', variables: { variables: MY_OBJECT }, metadata: {} },
                ],
                persistence_node_list: [
                    {
                        ...DTO,
                        mode: 'write',
                        entries: [
                            { key: 'whole', value: 'variables.my_object' },
                            { key: 'next', value: 'variables.' },
                        ],
                    },
                ],
            } as unknown as GraphDto;
            const ALL = ['variables.my_object', 'variables.my_object.user_id', 'variables.my_object.user_email'];
            const disabled = (): string[] =>
                Array.from(document.querySelectorAll<HTMLElement>('.vpf-item:disabled'), (item) => item.title);

            function openLoaded(): {
                panel: PersistenceNodePanelComponent;
                fixture: ComponentFixture<PersistenceNodePanelComponent>;
            } {
                const flowService = new FlowService();
                flowService.setFlow(mapGraphDtoToFlowModel(GRAPH));
                const node = flowService.nodes().find((flowNode) => flowNode.type === NodeType.PERSISTENCE);
                return createPanel(node as PersistenceNodeModel, { renderTemplate: true, flowService });
            }

            afterEach(() => delete (Element.prototype as Partial<Element>).scrollIntoView);

            it('loads the start node state the picker lists from', () => {
                const flowService = new FlowService();
                flowService.setFlow(mapGraphDtoToFlowModel(GRAPH));

                expect(flowService.startNodeInitialState()).toEqual({ variables: MY_OBJECT });
            });

            it('offers the object the other row uses, and its fields, all enabled', () => {
                const { panel, fixture } = openLoaded();

                typeValue(fixture, 'variables.', 1);
                expect(listed()).toEqual(ALL);
                expect(disabled()).toEqual([]);

                document.querySelector<HTMLElement>('.vpf-item')!.click();
                fixture.detectChanges();
                expect(entriesOf(panel).at(1).get('value')!.value).toBe('variables.my_object');
                expect(entriesOf(panel).at(1).get('value')!.valid).toBe(true);
                expect(panel.captureForValidation()).not.toBeNull();
            });

            it('picks a field with the arrow keys and Enter', () => {
                Element.prototype.scrollIntoView = vi.fn();
                const { panel, fixture } = openLoaded();
                const input = typeValue(fixture, 'variables.', 1);
                const press = (key: string): KeyboardEvent => {
                    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
                    input.dispatchEvent(event);
                    fixture.detectChanges();
                    return event;
                };

                // Other keys still reach the input.
                expect(press('a').defaultPrevented).toBe(false);
                press('ArrowUp');
                press('ArrowUp');
                press('Enter');

                expect(entriesOf(panel).at(1).get('value')!.value).toBe('variables.my_object.user_id');
                expect(listed()).toEqual([]);
            });

            it('picks nothing on Enter once the pointer has left the list while the prefill is untouched', () => {
                const { panel, fixture } = openLoaded();
                const input = typeValue(fixture, 'variables.', 1);
                document.querySelectorAll('.vpf-item')[2].dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
                document.querySelector('.vpf-list')!.dispatchEvent(new MouseEvent('mouseleave'));
                fixture.detectChanges();

                const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
                input.dispatchEvent(enter);
                fixture.detectChanges();

                // With nothing highlighted the picker leaves Enter alone, so it moves on: a row below.
                expect(entriesOf(panel).at(1).get('value')!.value).toBe('variables.');
                expect(enter.defaultPrevented).toBe(true);
                expect(entriesOf(panel).at(2).getRawValue()).toEqual({ key: '', value: 'variables.' });
            });

            it('wires the value input to the list as a combobox, and closes the list when focus leaves', () => {
                const { fixture } = openLoaded();
                const input = typeValue(fixture, 'variables.', 1);
                expect(input.getAttribute('aria-controls')).toBe(document.querySelector('.vpf-list')!.id);

                input.dispatchEvent(new FocusEvent('blur'));
                fixture.detectChanges();

                expect(listed()).toEqual([]);
                expect(input.getAttribute('aria-controls')).toBeNull();
                expect(input.getAttribute('aria-expanded')).toBe('false');
            });
        });

        it('leaves the key input to the stored key suggestions', () => {
            vi.useFakeTimers();
            const { fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.' }]), {
                renderTemplate: true,
                getEntries: () =>
                    of({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [{ key: 'profile_1' } as PersistenceTableEntryListItem],
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

    describe('variable snippets in a key placeholder', () => {
        // jsdom has no scrollIntoView, which the arrow keys call on the highlighted row.
        beforeEach(() => (Element.prototype.scrollIntoView = vi.fn()));
        afterEach(() => delete (Element.prototype as Partial<Element>).scrollIntoView);
        const initialState = { variables: { user: { id: 1 }, plan: 'free' } };
        const keyInput = (fixture: ComponentFixture<PersistenceNodePanelComponent>): HTMLInputElement =>
            fixture.nativeElement.querySelector('input[aria-label="Key"]');
        /** Types a key with the caret at `caret`, or at its end. */
        const typeKey = (
            fixture: ComponentFixture<PersistenceNodePanelComponent>,
            text: string,
            caret = text.length
        ): HTMLInputElement => {
            const input = keyInput(fixture);
            input.value = text;
            input.setSelectionRange(caret, caret);
            input.dispatchEvent(new Event('input'));
            fixture.detectChanges();
            return input;
        };
        const press = (
            fixture: ComponentFixture<PersistenceNodePanelComponent>,
            input: HTMLInputElement,
            key: string
        ): KeyboardEvent => {
            const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
            input.dispatchEvent(event);
            fixture.detectChanges();
            return event;
        };
        const listed = (): string[] =>
            Array.from(document.querySelectorAll<HTMLElement>('app-var-picker-flat .vpf-item'), (item) => item.title);
        const keyOf = (panel: PersistenceNodePanelComponent): string => entriesOf(panel).at(0).get('key')!.value;
        const openWithStoredKey = (): ReturnType<typeof createPanel> =>
            createPanel(nodeWith('write', [{ key: '', value: 'variables.plan' }]), {
                renderTemplate: true,
                getEntries: () =>
                    of({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [{ key: 'profile_1' } as PersistenceTableEntryListItem],
                    }),
                initialState,
            });

        it('opens the variable picker once variables. is typed inside a {, filtered by what follows', () => {
            const { fixture } = openWithStoredKey();

            typeKey(fixture, 'profile_{');
            expect(listed()).toEqual([]);

            const input = typeKey(fixture, 'profile_{variables.');
            expect(listed()).toEqual(['variables.user', 'variables.user.id', 'variables.plan']);
            expect(input.getAttribute('aria-expanded')).toBe('true');
            expect(input.getAttribute('aria-controls')).toBe(document.querySelector('.vpf-list')!.id);

            typeKey(fixture, 'profile_{variables.us');
            expect(listed()).toEqual(['variables.user', 'variables.user.id']);
        });

        it('inserts the clicked path and closes the placeholder, the caret after it', () => {
            const { panel, fixture } = openWithStoredKey();

            const input = typeKey(fixture, 'profile_{variables.us');
            document.querySelectorAll<HTMLElement>('.vpf-item')[1].click();
            fixture.detectChanges();

            expect(keyOf(panel)).toBe('profile_{variables.user.id}');
            expect(entriesOf(panel).at(0).get('key')!.dirty).toBe(true);
            expect(input.selectionStart).toBe('profile_{variables.user.id}'.length);
            expect(listed()).toEqual([]);
        });

        it('keeps a closing } that is already there, and the text after it', () => {
            const { panel, fixture } = openWithStoredKey();

            typeKey(fixture, 'p_{variables.us}_x', 'p_{variables.us'.length);
            document.querySelectorAll<HTMLElement>('.vpf-item')[1].click();
            fixture.detectChanges();

            expect(keyOf(panel)).toBe('p_{variables.user.id}_x');
        });

        it('offers nothing outside a placeholder, or in one closed before the caret', () => {
            const { fixture } = openWithStoredKey();

            typeKey(fixture, 'variables.');
            expect(listed()).toEqual([]);
            typeKey(fixture, 'p_{variables.plan}_variables.');
            expect(listed()).toEqual([]);

            typeKey(fixture, 'p_{variables.');
            expect(listed().length).toBe(3);
            typeKey(fixture, 'p_{variables.}');
            expect(listed()).toEqual([]);
        });

        it('picks with the arrow keys and Enter, and closes on Escape, as in a value field', () => {
            const { panel, fixture } = openWithStoredKey();

            let input = typeKey(fixture, 'p_{variables.');
            press(fixture, input, 'Escape');
            expect(listed()).toEqual([]);

            input = typeKey(fixture, 'p_{variables.p');
            press(fixture, input, 'ArrowDown');
            const enter = press(fixture, input, 'Enter');

            expect(enter.defaultPrevented).toBe(true);
            expect(keyOf(panel)).toBe('p_{variables.plan}');
            expect(listed()).toEqual([]);
            // The pick took Enter, so no row was added.
            expect(entriesOf(panel).length).toBe(1);
        });

        it('highlights nothing on the text that opened it, and the first snippet once typed past it, which Enter picks', () => {
            const { panel, fixture } = openWithStoredKey();

            typeKey(fixture, 'p_{variables.');
            expect(document.querySelectorAll('.vpf-item--highlighted').length).toBe(0);
            const input = typeKey(fixture, 'p_{variables.user.');
            expect(listed()).toEqual(['variables.user.id']);
            expect(press(fixture, input, 'Enter').defaultPrevented).toBe(true);

            expect(keyOf(panel)).toBe('p_{variables.user.id}');
            expect(entriesOf(panel).length).toBe(1);
        });

        it('leaves Enter to the row when no snippet matches, which moves on to the variable', () => {
            const { panel, fixture } = openWithStoredKey();

            const input = typeKey(fixture, 'p_{variables.nothing');
            expect(listed()).toEqual([]);
            input.focus();
            expect(press(fixture, input, 'Enter').defaultPrevented).toBe(true);

            expect(keyOf(panel)).toBe('p_{variables.nothing');
            expect(document.activeElement?.getAttribute('aria-label')).toBe('Variable path');
        });

        it('highlights nothing on an empty placeholder, the first snippet once one is typed', () => {
            const { fixture } = openWithStoredKey();
            const highlighted = (): string[] =>
                Array.from(document.querySelectorAll<HTMLElement>('.vpf-item--highlighted'), (item) => item.title);

            typeKey(fixture, 'p_{variables.');
            expect(highlighted()).toEqual([]);
            typeKey(fixture, 'p_{variables.u');
            expect(highlighted()).toEqual(['variables.user']);
        });

        it('follows the caret into a placeholder without preselecting, as moving it is no edit', () => {
            const { fixture } = createPanel(
                nodeWith('write', [{ key: 'p_{variables.user', value: 'variables.plan' }]),
                {
                    renderTemplate: true,
                    initialState,
                }
            );
            const input = keyInput(fixture);
            input.focus();
            input.setSelectionRange('p_{variables.use'.length, 'p_{variables.use'.length);
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowLeft', bubbles: true }));
            fixture.detectChanges();

            expect(listed()).toEqual(['variables.user', 'variables.user.id']);
            expect(document.querySelectorAll('.vpf-item--highlighted').length).toBe(0);
            expect(press(fixture, input, 'Enter').defaultPrevented).toBe(true);
            // The picker left Enter alone, so the row moved on to its variable.
            expect(entriesOf(fixture.componentInstance).at(0).get('key')!.value).toBe('p_{variables.user');
            expect(document.activeElement?.getAttribute('aria-label')).toBe('Variable path');
        });

        it('shows the stored key suggestions or the snippets, never both', () => {
            vi.useFakeTimers();
            const { fixture } = openWithStoredKey();
            const suggestions = (): string[] =>
                Array.from(document.querySelectorAll('.vdo-item'), (item) => item.textContent!.trim());

            typeKey(fixture, 'pro');
            vi.advanceTimersByTime(250);
            fixture.detectChanges();
            expect(suggestions()).toEqual(['profile_1']);
            expect(listed()).toEqual([]);

            // A { closes the stored key suggestions at once, without waiting for a search.
            typeKey(fixture, 'pro{');
            expect(suggestions()).toEqual([]);
            typeKey(fixture, 'pro{variables.');
            vi.advanceTimersByTime(250);
            fixture.detectChanges();
            expect(suggestions()).toEqual([]);
            expect(listed().length).toBe(3);
        });

        it('allows spaces after the {, as crew does', () => {
            const { panel, fixture } = openWithStoredKey();

            typeKey(fixture, 'p_{ variables.pl');
            expect(listed()).toEqual(['variables.plan']);
            document.querySelector<HTMLElement>('.vpf-item')!.click();
            fixture.detectChanges();

            expect(keyOf(panel)).toBe('p_{variables.plan}');
        });

        it('follows the caret when it moves without typing, by arrow key or click', () => {
            const { fixture } = openWithStoredKey();
            const input = typeKey(fixture, 'p_{variables.plan}_{variables.u');
            expect(listed()).toEqual(['variables.user', 'variables.user.id']);

            // Back inside the first placeholder: its own text filters the list.
            input.setSelectionRange('p_{variables.pl'.length, 'p_{variables.pl'.length);
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowLeft' }));
            fixture.detectChanges();
            expect(listed()).toEqual(['variables.plan']);

            // Out of every placeholder: the list closes.
            input.setSelectionRange(1, 1);
            input.dispatchEvent(new MouseEvent('click'));
            fixture.detectChanges();
            expect(listed()).toEqual([]);

            // Other keys that don't move the caret leave the list alone.
            typeKey(fixture, 'p_{variables.');
            input.setSelectionRange(1, 1);
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Shift' }));
            fixture.detectChanges();
            expect(listed().length).toBe(3);
        });

        it('closes when focus leaves the key', () => {
            const { fixture } = openWithStoredKey();

            const input = typeKey(fixture, 'p_{variables.');
            input.dispatchEvent(new FocusEvent('blur'));
            fixture.detectChanges();

            expect(listed()).toEqual([]);
            expect(input.getAttribute('aria-expanded')).toBe('false');
        });
    });

    describe('Enter moves through the entries', () => {
        // jsdom has no scrollIntoView, which the arrow keys call on the highlighted row.
        beforeEach(() => (Element.prototype.scrollIntoView = vi.fn()));
        afterEach(() => delete (Element.prototype as Partial<Element>).scrollIntoView);
        const fieldsOf = (fixture: ComponentFixture<PersistenceNodePanelComponent>, row: number): HTMLInputElement[] =>
            Array.from(fixture.nativeElement.querySelectorAll('.entry-row')[row].querySelectorAll('input'));
        const pressEnter = (
            fixture: ComponentFixture<PersistenceNodePanelComponent>,
            input: HTMLInputElement
        ): KeyboardEvent => {
            input.focus();
            const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
            input.dispatchEvent(event);
            fixture.detectChanges();
            return event;
        };
        const labels = (inputs: HTMLInputElement[]): string[] =>
            inputs.map((input) => input.getAttribute('aria-label')!);

        it('goes from the key to the variable of the same row in write', () => {
            const { panel, fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.user' }]), {
                renderTemplate: true,
            });
            const [key, value] = fieldsOf(fixture, 0);
            expect(labels([key, value])).toEqual(['Key', 'Variable path']);

            expect(pressEnter(fixture, key).defaultPrevented).toBe(true);

            expect(document.activeElement).toBe(value);
            expect(entriesOf(panel).length).toBe(1);
        });

        it('goes from the variable to the key of the same row in read, which shows variable = key', () => {
            const { panel, fixture } = createPanel(nodeWith('read', [{ key: 'profile', value: 'variables.user' }]), {
                renderTemplate: true,
            });
            const [value, key] = fieldsOf(fixture, 0);
            expect(labels([value, key])).toEqual(['Variable path', 'Key']);

            pressEnter(fixture, value);

            expect(document.activeElement).toBe(key);
            expect(entriesOf(panel).length).toBe(1);
        });

        for (const mode of ['read', 'write'] as const) {
            it(`adds a row right below from the right field in ${mode}, prefilled like Add key, its left field focused`, () => {
                const { panel, fixture } = createPanel(
                    nodeWith(mode, [
                        { key: 'a', value: 'variables.a' },
                        { key: 'b', value: 'variables.b' },
                    ]),
                    { renderTemplate: true }
                );

                pressEnter(fixture, fieldsOf(fixture, 0)[1]);
                TestBed.tick();

                expect(entriesOf(panel).getRawValue()).toEqual([
                    { key: 'a', value: 'variables.a' },
                    { key: '', value: 'variables.' },
                    { key: 'b', value: 'variables.b' },
                ]);
                expect(document.activeElement).toBe(fieldsOf(fixture, 1)[0]);
            });
        }

        it('adds a row below from the key in delete and focuses its key', () => {
            const { panel, fixture } = createPanel(nodeWith('delete', [{ key: 'a' }, { key: 'b' }]), {
                renderTemplate: true,
            });

            pressEnter(fixture, fieldsOf(fixture, 0)[0]);
            TestBed.tick();

            expect(entriesOf(panel).getRawValue()).toEqual([{ key: 'a' }, { key: '' }, { key: 'b' }]);
            expect(document.activeElement).toBe(fieldsOf(fixture, 1)[0]);
        });

        it('lets an open stored key suggestion list take Enter to pick', () => {
            vi.useFakeTimers();
            const { panel, fixture } = createPanel(nodeWith('write', [{ key: '', value: 'variables.a' }]), {
                renderTemplate: true,
                getEntries: () =>
                    of({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [{ key: 'greeting' } as PersistenceTableEntryListItem],
                    }),
            });
            const key = fieldsOf(fixture, 0)[0];
            key.focus();
            key.value = 'gre';
            key.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(250);
            fixture.detectChanges();

            pressEnter(fixture, key);

            expect(entriesOf(panel).at(0).get('key')!.value).toBe('greeting');
            expect(document.activeElement).toBe(key);
        });

        for (const mode of ['read', 'write'] as const) {
            it(`moves on in ${mode} from the untouched variables. prefill, the open picker highlighting nothing`, () => {
                const { panel, fixture } = createPanel(nodeWith(mode, [{ key: 'a', value: 'variables.' }]), {
                    renderTemplate: true,
                    initialState: { variables: { plan: 'free' } },
                });
                const valueField = fieldsOf(fixture, 0).find(
                    (field) => field.getAttribute('aria-label') === 'Variable path'
                )!;
                valueField.focus();
                fixture.detectChanges();
                expect(document.querySelector('app-var-picker-flat')).not.toBeNull();
                expect(document.querySelectorAll('.vpf-item--highlighted').length).toBe(0);

                expect(pressEnter(fixture, valueField).defaultPrevented).toBe(true);
                TestBed.tick();

                expect(entriesOf(panel).at(0).get('value')!.value).toBe('variables.');
                // Read shows `variables.x = key`, so its variable moves on to the key; write's adds a row.
                if (mode === 'read') {
                    expect(document.activeElement).toBe(fieldsOf(fixture, 0)[1]);
                    expect(entriesOf(panel).length).toBe(1);
                } else {
                    expect(entriesOf(panel).length).toBe(2);
                    expect(document.activeElement).toBe(fieldsOf(fixture, 1)[0]);
                }
            });
        }

        it('lets the open variable picker take Enter to pick its first variable once something is typed', () => {
            const { panel, fixture } = createPanel(nodeWith('write', [{ key: 'a', value: 'variables.' }]), {
                renderTemplate: true,
                initialState: { variables: { plan: 'free' } },
            });
            const value = fieldsOf(fixture, 0)[1];
            value.focus();
            fixture.detectChanges();
            value.value = 'variables.p';
            value.dispatchEvent(new Event('input'));
            fixture.detectChanges();

            pressEnter(fixture, value);

            expect(entriesOf(panel).getRawValue()).toEqual([{ key: 'a', value: 'variables.plan' }]);
            expect(document.activeElement).toBe(value);
        });

        for (const mode of ['read', 'write'] as const) {
            it(`moves on in ${mode} when the open variable picker has nothing to pick`, () => {
                const { panel, fixture } = createPanel(nodeWith(mode, [{ key: 'a', value: 'variables.nothing' }]), {
                    renderTemplate: true,
                    initialState: { variables: { plan: 'free' } },
                });
                const valueField = fieldsOf(fixture, 0).find(
                    (field) => field.getAttribute('aria-label') === 'Variable path'
                )!;
                valueField.focus();
                valueField.dispatchEvent(new Event('input'));
                fixture.detectChanges();
                expect(document.querySelector('app-var-picker-flat')).not.toBeNull();

                expect(pressEnter(fixture, valueField).defaultPrevented).toBe(true);
                TestBed.tick();

                expect(entriesOf(panel).at(0).get('value')!.value).toBe('variables.nothing');
                // Read shows `variables.x = key`, so its variable moves on to the key; write's adds a row.
                if (mode === 'read') {
                    expect(document.activeElement).toBe(fieldsOf(fixture, 0)[1]);
                    expect(entriesOf(panel).length).toBe(1);
                } else {
                    expect(entriesOf(panel).length).toBe(2);
                    expect(document.activeElement).toBe(fieldsOf(fixture, 1)[0]);
                }
            });
        }

        // Renders 500 rows, as the Add key limit spec does.
        it('adds no row at the key limit, where the limit message shows', { timeout: 20_000 }, () => {
            const { panel, fixture } = createPanel(
                nodeWith(
                    'delete',
                    Array.from({ length: 500 }, (_, index) => ({ key: `k${index}` }))
                ),
                { renderTemplate: true }
            );

            expect(pressEnter(fixture, fieldsOf(fixture, 499)[0]).defaultPrevented).toBe(true);
            TestBed.tick();

            expect(entriesOf(panel).length).toBe(500);
            expect(hintsOf(fixture)).toEqual(['A Key-Value node can have at most 500 keys']);
        });
    });

    describe('key help', () => {
        const KEY_HELP = 'Use {variables.name} to insert a variable into the key';
        const helpsOf = (fixture: ComponentFixture<PersistenceNodePanelComponent>): string[][] =>
            Array.from(fixture.nativeElement.querySelectorAll('.entry-row'), (row: Element) =>
                Array.from(row.querySelectorAll('.entry-help'), (help) => help.textContent!.trim())
            );
        const keyOfRow = (fixture: ComponentFixture<PersistenceNodePanelComponent>, row: number): HTMLInputElement =>
            fixture.nativeElement.querySelectorAll('input[aria-label="Key"]')[row];
        const focusKey = (fixture: ComponentFixture<PersistenceNodePanelComponent>, row: number): HTMLInputElement => {
            const input = keyOfRow(fixture, row);
            input.focus();
            fixture.detectChanges();
            return input;
        };
        const typeKey = (
            fixture: ComponentFixture<PersistenceNodePanelComponent>,
            row: number,
            text: string
        ): HTMLInputElement => {
            const input = focusKey(fixture, row);
            input.value = text;
            input.dispatchEvent(new Event('input'));
            fixture.detectChanges();
            return input;
        };

        for (const mode of ['read', 'write', 'delete'] as const) {
            it(`shows under the new row's key in ${mode} once Add key focuses it`, () => {
                const entries = mode === 'delete' ? [{ key: 'a' }] : [{ key: 'a', value: 'variables.a' }];
                const { fixture } = createPanel(nodeWith(mode, entries), { renderTemplate: true });
                expect(helpsOf(fixture)).toEqual([[]]);

                fixture.nativeElement.querySelector('.add-entry').click();
                fixture.detectChanges();
                TestBed.tick();
                fixture.detectChanges();

                expect(document.activeElement).toBe(keyOfRow(fixture, 1));
                expect(helpsOf(fixture)).toEqual([[], [KEY_HELP]]);
            });
        }

        it('stays under the key focused last only, also after blur, so a long list carries one line', () => {
            const { fixture } = createPanel(
                nodeWith('write', [
                    { key: 'a', value: 'variables.a' },
                    { key: 'b', value: 'variables.b' },
                    { key: 'c', value: 'variables.c' },
                ]),
                { renderTemplate: true }
            );

            focusKey(fixture, 2);
            expect(helpsOf(fixture)).toEqual([[], [], [KEY_HELP]]);
            focusKey(fixture, 0);
            expect(helpsOf(fixture)).toEqual([[KEY_HELP], [], []]);

            keyOfRow(fixture, 0).blur();
            fixture.detectChanges();
            expect(helpsOf(fixture)).toEqual([[KEY_HELP], [], []]);
        });

        it('goes with its row when the row is removed', () => {
            const { fixture } = createPanel(
                nodeWith('write', [
                    { key: 'a', value: 'variables.a' },
                    { key: 'b', value: 'variables.b' },
                ]),
                { renderTemplate: true }
            );
            focusKey(fixture, 0);

            fixture.nativeElement.querySelector('.remove-entry').click();
            fixture.detectChanges();

            expect(helpsOf(fixture)).toEqual([[]]);
        });

        it('gives way to a hint or an error on its key, and comes back once it is fixed', () => {
            const { fixture } = createPanel(
                nodeWith('write', [
                    { key: 'a', value: 'variables.a' },
                    { key: 'b', value: 'variables.b' },
                ]),
                { renderTemplate: true }
            );

            let input = typeKey(fixture, 1, 'b_{variables.a');
            expect(helpsOf(fixture)).toEqual([[], []]);
            expect(hintsOf(fixture)).toEqual(['Close each { with } around a state path, like {variables.user.id}']);

            input = typeKey(fixture, 1, 'b-c');
            expect(helpsOf(fixture)).toEqual([[], []]);
            expect(hintsOf(fixture)).toEqual([
                'Use letters, digits and _ outside {placeholders}, not starting with a digit',
            ]);

            // A key repeated in write, which both rows flag.
            input = typeKey(fixture, 1, 'a');
            expect(helpsOf(fixture)).toEqual([[], []]);
            expect(hintsOf(fixture)).toEqual([
                'Duplicate key — use a different key',
                'Duplicate key — use a different key',
            ]);

            // Too long: only the red border shows, which the help still gives way to once touched.
            input = typeKey(fixture, 1, 'k'.repeat(PERSISTENCE_KEY_MAX_LENGTH + 1));
            input.blur();
            entriesOf(fixture.componentInstance).at(1).get('key')!.markAsTouched();
            fixture.detectChanges();
            expect(helpsOf(fixture)).toEqual([[], []]);

            typeKey(fixture, 1, 'b_{variables.a}');
            expect(helpsOf(fixture)).toEqual([[], [KEY_HELP]]);
        });
    });

    describe('key highlight', () => {
        const keyInput = (fixture: ComponentFixture<PersistenceNodePanelComponent>): HTMLInputElement =>
            fixture.nativeElement.querySelector('input[aria-label="Key"]');
        const backdrop = (fixture: ComponentFixture<PersistenceNodePanelComponent>): HTMLElement =>
            fixture.nativeElement.querySelector('.key-backdrop');
        const highlighted = (fixture: ComponentFixture<PersistenceNodePanelComponent>): string[] =>
            Array.from(backdrop(fixture).querySelectorAll('.vht-variable'), (span) => span.textContent!);
        const typeKey = (fixture: ComponentFixture<PersistenceNodePanelComponent>, text: string): void => {
            keyInput(fixture).value = text;
            keyInput(fixture).dispatchEvent(new Event('input'));
            fixture.detectChanges();
        };

        it('marks the placeholders that are state paths the way the task node marks variables, the rest as plain text', () => {
            const { fixture } = createPanel(nodeWith('write', [{ key: 'profile', value: 'variables.user' }]), {
                renderTemplate: true,
            });

            typeKey(fixture, 'profile_{variables.user.id}_{user.id}_{variables._secret}<b>x</b>');

            expect(highlighted(fixture)).toEqual(['{variables.user.id}']);
            expect(backdrop(fixture).textContent).toBe(
                'profile_{variables.user.id}_{user.id}_{variables._secret}<b>x</b>'
            );
            expect(backdrop(fixture).querySelector('b')).toBeNull();
            expect(backdrop(fixture).getAttribute('aria-hidden')).toBe('true');
        });

        it('draws a loaded key, and a key with no placeholders as plain text', () => {
            const { fixture } = createPanel(
                nodeWith('delete', [{ key: 'a_{variables.a}_{variables.b[0]}' }, { key: 'plain' }]),
                { renderTemplate: true }
            );
            const backdrops: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('.key-backdrop'));

            expect(
                backdrops.map((row) => Array.from(row.querySelectorAll('.vht-variable'), (span) => span.textContent))
            ).toEqual([['{variables.a}', '{variables.b[0]}'], []]);
            expect(backdrops[1].textContent).toBe('plain');
        });

        it('keeps the key form control, its hints and the stored key suggestions', () => {
            vi.useFakeTimers();
            const { panel, fixture } = createPanel(nodeWith('write', [{ key: '', value: 'variables.user' }]), {
                renderTemplate: true,
                getEntries: () =>
                    of({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [{ key: 'greeting' } as PersistenceTableEntryListItem],
                    }),
            });

            typeKey(fixture, 'profile_{user.id}');
            expect(hintsOf(fixture)).toContain('Use {variables.user.id}');
            expect(entriesOf(panel).at(0).get('key')!.hasError('keyTemplate')).toBe(true);
            expect(highlighted(fixture)).toEqual([]);

            typeKey(fixture, 'gre');
            vi.advanceTimersByTime(250);
            fixture.detectChanges();
            expect(keyInput(fixture).getAttribute('aria-expanded')).toBe('true');
            document.querySelector<HTMLElement>('.vdo-item')!.click();
            fixture.detectChanges();

            expect(entriesOf(panel).at(0).get('key')!.value).toBe('greeting');
            expect(keyInput(fixture).value).toBe('greeting');
            expect(backdrop(fixture).textContent).toBe('greeting');
        });
    });

    describe('mode permissions', () => {
        const { Create, Read, Update, Delete } = ActionCode;
        const modeNames = (panel: PersistenceNodePanelComponent): string[] =>
            panel['modeItems']().map((item) => item.name);
        const notice = (fixture: ComponentFixture<PersistenceNodePanelComponent>): string | null =>
            fixture.nativeElement.querySelector('.permission-notice').textContent.trim() || null;
        const lockIcon = (fixture: ComponentFixture<PersistenceNodePanelComponent>): HTMLElement | null =>
            fixture.nativeElement.querySelector('.permission-notice .ti-lock');
        const lockable = (panel: PersistenceNodePanelComponent): boolean[] =>
            ['mode', 'persistence_table', 'entries'].map((name) => panel.form.get(name)!.disabled);
        const readNode = nodeWith('read', [{ key: 'profile', value: 'variables.user' }]);
        const writeNode = nodeWith('write', [{ key: 'profile', value: 'variables.user' }]);

        it.each<[string, ActionCode[], string[]]>([
            ['View', [Read], ['Read']],
            ['View, Create and Edit', [Read, Create, Update], ['Read', 'Write']],
            // Write needs both Create and Edit.
            ['View and Create', [Read, Create], ['Read']],
            ['View and Delete', [Read, Delete], ['Read', 'Delete']],
            // As for a superadmin too: PermissionsService.can() allows a superadmin every action.
            ['every action', [Create, Read, Update, Delete], ['Read', 'Write', 'Delete']],
        ])('offers only the modes the user may configure, with %s', (_label, actions, names) => {
            const { panel, fixture } = createPanel(readNode, { renderTemplate: true, actions });

            expect(modeNames(panel)).toEqual(names);
            expect(lockable(panel)).toEqual([false, false, false]);
            expect(notice(fixture)).toBeNull();
        });

        it('locks mode, table and keys of a node whose saved mode the user may not configure, keeping it as saved', () => {
            const { panel, fixture } = createPanel(writeNode, { renderTemplate: true, actions: [Read] });

            expect(notice(fixture)).toBe('Changing a Write node needs Create and Edit permission on Key-Value Tables.');
            expect(modeNames(panel)).toEqual(['Write']);
            expect(lockable(panel)).toEqual([true, true, true]);
            expect(panel.form.get('node_name')!.enabled).toBe(true);
            expect(fixture.nativeElement.querySelector('.dropdown-trigger').disabled).toBe(true);
            expect(fixture.nativeElement.querySelector('.add-entry').disabled).toBe(true);
            expect(fixture.nativeElement.querySelector('.remove-entry').disabled).toBe(true);
            expect(fixture.nativeElement.querySelector('input[aria-label="Key"]').disabled).toBe(true);
            expect(fixture.nativeElement.querySelector('.entry-row').classList).toContain('locked');

            // A locked node with valid entries still passes the flow save's panel check.
            expect(panel.captureForValidation()).not.toBeNull();

            // The name is still editable, and the save keeps mode, table and keys as they were.
            panel.form.get('node_name')!.setValue('Renamed');
            const saved = panel.onSave()!;
            expect(saved.node_name).toBe('Renamed');
            expect(saved.data).toEqual({
                mode: 'write',
                persistence_table: 3,
                entries: [{ key: 'profile', value: 'variables.user' }],
            });
        });

        it('locks a delete node without the Delete permission', () => {
            const { panel, fixture } = createPanel(nodeWith('delete', [{ key: 'profile' }]), {
                renderTemplate: true,
                actions: [Read, Create, Update],
            });

            expect(notice(fixture)).toBe('Changing a Delete node needs Delete permission on Key-Value Tables.');
            expect(panel.form.get('entries')!.disabled).toBe(true);
            expect(panel.onSave()!.data).toEqual({
                mode: 'delete',
                persistence_table: 3,
                entries: [{ key: 'profile' }],
            });
        });

        it('locks the node and says so without the View permission, whatever else the user may do', () => {
            const { panel, fixture } = createPanel(writeNode, { renderTemplate: true, actions: [Create, Update] });

            expect(notice(fixture)).toBe('You need View permission on Key-Value Tables to configure this node.');
            expect(lockable(panel)).toEqual([true, true, true]);
            expect(panel.form.get('node_name')!.enabled).toBe(true);
        });

        it('follows permissions that arrive or change after the panel opens, e.g. on an org switch', () => {
            vi.useFakeTimers();
            const { panel, fixture, permittedActions, triggerAutosave } = createPanel(writeNode, {
                renderTemplate: true,
                actions: [],
            });
            expect(notice(fixture)).toBe('You need View permission on Key-Value Tables to configure this node.');
            expect(lockIcon(fixture)?.getAttribute('aria-hidden')).toBe('true');
            expect(lockable(panel)).toEqual([true, true, true]);

            permittedActions.set([Create, Read, Update, Delete]);
            fixture.detectChanges();
            vi.advanceTimersByTime(1000);

            // The status container stays, empty, so the next notice is announced.
            expect(notice(fixture)).toBeNull();
            expect(lockIcon(fixture)).toBeNull();
            expect(fixture.nativeElement.querySelector('.permission-notice').getAttribute('role')).toBe('status');
            expect(lockable(panel)).toEqual([false, false, false]);
            expect(triggerAutosave).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(false);

            permittedActions.set([Read]);
            fixture.detectChanges();

            expect(notice(fixture)).toBe('Changing a Write node needs Create and Edit permission on Key-Value Tables.');
            expect(lockIcon(fixture)).not.toBeNull();
            expect(lockable(panel)).toEqual([true, true, true]);
        });

        it('puts the saved mode, table and keys back when a relock comes mid-edit', () => {
            vi.useFakeTimers();
            const { panel, fixture, permittedActions, triggerAutosave } = createPanel(writeNode, {
                renderTemplate: true,
            });
            panel.form.get('mode')!.setValue('delete');
            panel.form.get('persistence_table')!.setValue(4);
            entriesOf(panel).at(0).patchValue({ key: 'edited' });
            fixture.detectChanges();
            vi.advanceTimersByTime(1000);
            triggerAutosave.mockClear();

            permittedActions.set([Read]);
            fixture.detectChanges();
            vi.advanceTimersByTime(1000);

            expect(lockable(panel)).toEqual([true, true, true]);
            expect(panel.onSave()!.data).toEqual({
                mode: 'write',
                persistence_table: 3,
                entries: [{ key: 'profile', value: 'variables.user' }],
            });
            // The rows are the saved mode's again: key = variable, the key drawn as saved.
            expect(fixture.nativeElement.querySelectorAll('.entry-row input').length).toBe(2);
            expect(fixture.nativeElement.querySelector('.key-backdrop').textContent).toBe('profile');
            expect(triggerAutosave).not.toHaveBeenCalled();
        });

        it('lets a locked node with an old invalid key past the panel check, which the flow save still refuses', () => {
            const node = nodeWith('write', [{ key: 'user-1', value: 'variables.user' }]);
            const { panel } = createPanel(node, { actions: [Read] });

            const captured = panel.captureForValidation();

            expect(captured).not.toBeNull();
            expect(invalidPersistenceNodeMessages([captured!])).toEqual([
                '"Persistence #1" has invalid keys or variable paths',
            ]);
        });
    });

    describe('table picker', () => {
        const table = (id: number, name: string): PersistenceTable =>
            ({ id, name, description: '', entry_count: 0 }) as PersistenceTable;
        const TABLES = [table(3, 'profiles'), table(4, 'orders')];

        const trigger = (fixture: ComponentFixture<PersistenceNodePanelComponent>): HTMLElement =>
            fixture.nativeElement.querySelector('.dropdown-trigger');
        const tableHint = (fixture: ComponentFixture<PersistenceNodePanelComponent>): Element | null =>
            fixture.nativeElement.querySelector('.table-hint');
        const openDropdown = (fixture: ComponentFixture<PersistenceNodePanelComponent>): void => {
            trigger(fixture).click();
            fixture.detectChanges();
        };
        const rowNames = (): string[] =>
            Array.from(document.querySelectorAll('.select-dropdown__row-name'), (row) => row.textContent!.trim());
        const clickRow = (name: string): void =>
            Array.from(document.querySelectorAll<HTMLElement>('.select-dropdown__row'))
                .find((row) => row.textContent!.trim() === name)!
                .click();
        const selectedRowNames = (): string[] =>
            Array.from(document.querySelectorAll('.select-dropdown__row--selected'), (row) => row.textContent!.trim());
        const createButton = (): HTMLButtonElement | null =>
            document.querySelector<HTMLButtonElement>('.select-dropdown__action');

        it('shows the selected table and sets the control from the dropdown', () => {
            const { panel, fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                tables: TABLES,
            });
            expect(trigger(fixture).textContent!.trim()).toBe('profiles');

            openDropdown(fixture);
            expect(rowNames()).toEqual(['No table', 'profiles', 'orders']);
            clickRow('orders');
            fixture.detectChanges();

            const control = panel.form.get('persistence_table')!;
            expect(control.value).toBe(4);
            expect(control.dirty).toBe(true);
            expect(trigger(fixture).textContent!.trim()).toBe('orders');
            expect(panel.onSave()!.data.persistence_table).toBe(4);
        });

        it('clears the table with "No table", which then asks for one', () => {
            vi.useFakeTimers();
            const { panel, fixture, triggerAutosave } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                tables: TABLES,
            });
            expect(tableHint(fixture)).toBeNull();

            openDropdown(fixture);
            clickRow('No table');
            fixture.detectChanges();

            const control = panel.form.get('persistence_table')!;
            expect(control.value).toBeNull();
            expect(control.dirty).toBe(true);
            expect(trigger(fixture).textContent!.trim()).toBe('Select a table');
            expect(tableHint(fixture)?.textContent!.trim()).toBe('Select a table for this node to run');
            vi.advanceTimersByTime(300);
            expect(triggerAutosave).toHaveBeenCalledTimes(1);
            expect(panel.onSave()!.data.persistence_table).toBeNull();

            openDropdown(fixture);
            expect(selectedRowNames()).toEqual(['No table']);
        });

        it('asks for a table while none is selected', () => {
            const { fixture } = createPanel(mapPersistenceNodeToModel({ ...DTO, persistence_table: null }), {
                renderTemplate: true,
                tables: TABLES,
            });

            expect(trigger(fixture).textContent!.trim()).toBe('Select a table');
            expect(tableHint(fixture)?.textContent!.trim()).toBe('Select a table for this node to run');
        });

        it('shows the placeholder, without the hint, for a table that is not in the list', () => {
            const { fixture } = createPanel(mapPersistenceNodeToModel({ ...DTO, persistence_table: 99 }), {
                renderTemplate: true,
                tables: TABLES,
            });

            expect(trigger(fixture).textContent!.trim()).toBe('Select a table');
            expect(tableHint(fixture)).toBeNull();
        });

        it('offers no "Create table" without the right to create one', () => {
            const { fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                tables: TABLES,
                actions: [ActionCode.Read, ActionCode.Update, ActionCode.Delete],
            });

            openDropdown(fixture);

            expect(rowNames()).toEqual(['No table', 'profiles', 'orders']);
            expect(createButton()).toBeNull();
        });

        it('offers "Create table" with the right to create one', () => {
            const { fixture } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                tables: TABLES,
            });

            openDropdown(fixture);

            // Only the "+" shows; its name and tooltip still say what it does.
            expect(createButton()?.textContent!.trim()).toBe('');
            expect(createButton()?.getAttribute('aria-label')).toBe('Create table');
            expect(createButton()?.title).toBe('Create table');
            expect(createButton()?.querySelector('app-svg-icon')).not.toBeNull();
        });

        it('adds a created table to the list and selects it', () => {
            const created = new Subject<PersistenceTable | null>();
            const { panel, fixture, openDialog, reloadTables, storedTables } = createPanel(
                mapPersistenceNodeToModel(DTO),
                { renderTemplate: true, tables: TABLES, createdTable: created }
            );
            reloadTables.mockImplementation(() => {
                storedTables.set([...TABLES, table(7, 'sessions')]);
                return of(storedTables());
            });

            openDropdown(fixture);
            createButton()!.click();
            fixture.detectChanges();
            expect(openDialog).toHaveBeenCalledTimes(1);
            // The dropdown closes, so it is not left open under the dialog.
            expect(createButton()).toBeNull();

            created.next(table(7, 'sessions'));
            fixture.detectChanges();

            const control = panel.form.get('persistence_table')!;
            expect(control.value).toBe(7);
            expect(control.dirty).toBe(true);
            // A reload, not loadTables(): a load in flight may predate the new table.
            expect(reloadTables).toHaveBeenCalledTimes(1);
            expect(trigger(fixture).textContent!.trim()).toBe('sessions');
            openDropdown(fixture);
            expect(rowNames()).toEqual(['No table', 'profiles', 'orders', 'sessions']);
        });

        it('keeps showing the reload after a create when the load from opening ends first', () => {
            const openingLoad = new Subject<PersistenceTable[]>();
            const reload = new Subject<PersistenceTable[]>();
            const created = new Subject<PersistenceTable | null>();
            const { fixture, storedTables } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                createdTable: created,
                tablesLoad: openingLoad,
                tablesReload: reload,
            });
            expect(trigger(fixture).textContent!.trim()).toBe('Loading tables...');

            openDropdown(fixture);
            createButton()!.click();
            created.next(table(7, 'sessions'));
            fixture.detectChanges();

            // The storage drops this late response; what matters is that it ends before the reload.
            openingLoad.next(TABLES);
            openingLoad.complete();
            fixture.detectChanges();
            expect(trigger(fixture).textContent!.trim()).toBe('Loading tables...');

            const withCreated = [...TABLES, table(7, 'sessions')];
            storedTables.set(withCreated);
            reload.next(withCreated);
            reload.complete();
            fixture.detectChanges();
            expect(trigger(fixture).textContent!.trim()).toBe('sessions');
        });

        it('keeps the selection when the dialog is cancelled', () => {
            const created = new Subject<PersistenceTable | null>();
            const { panel, fixture, reloadTables } = createPanel(mapPersistenceNodeToModel(DTO), {
                renderTemplate: true,
                tables: TABLES,
                createdTable: created,
            });

            openDropdown(fixture);
            createButton()!.click();
            created.next(null);
            fixture.detectChanges();

            const control = panel.form.get('persistence_table')!;
            expect(control.value).toBe(3);
            expect(control.dirty).toBe(false);
            expect(reloadTables).not.toHaveBeenCalled();
            expect(trigger(fixture).textContent!.trim()).toBe('profiles');
        });
    });
});

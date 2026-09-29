import { Dialog } from '@angular/cdk/dialog';
import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { NgTemplateOutlet } from '@angular/common';
import {
    afterNextRender,
    Component,
    computed,
    effect,
    ElementRef,
    inject,
    Injector,
    signal,
    untracked,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    FormArray,
    FormGroup,
    ReactiveFormsModule,
    ValidationErrors,
    ValidatorFn,
    Validators,
} from '@angular/forms';
import {
    AppSvgIconComponent,
    CustomInputComponent,
    SelectComponent,
    SelectDropdownComponent,
    SelectDropdownHeaderAction,
    SelectDropdownListItem,
    SelectDropdownTriggerDirective,
    SelectItem,
    TooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import {
    catchError,
    debounceTime,
    distinctUntilChanged,
    finalize,
    map,
    Observable,
    of,
    skip,
    startWith,
    Subject,
    Subscription,
    switchMap,
} from 'rxjs';

import { KeyValueTableDialogComponent } from '../../../../features/key-value-tables/components/key-value-table-dialog/key-value-table-dialog.component';
import {
    KeyValueEntryLookupResponse,
    KeyValueTable,
} from '../../../../features/key-value-tables/models/key-value-table.model';
import { KeyValueTablesApiService } from '../../../../features/key-value-tables/services/key-value-tables-api.service';
import { KeyValueTablesStorageService } from '../../../../features/key-value-tables/services/key-value-tables-storage.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import {
    canConfigureMode,
    duplicateWriteKeys,
    existenceHint,
    isEmptyEntry,
    isNestedPath,
    isSameLookupRequest,
    isStatePath,
    isStaticKey,
    KEY_PLACEHOLDER_HINT,
    KEY_VALUE_KEY_MAX_LENGTH,
    KEY_VALUE_MAX_KEYS,
    keyError,
    keyOccurrences,
    keyTemplateHint,
    LookupRequest,
    normalizeEntry,
    readTargetConflict,
    validReadTarget,
    VALUE_PREFILL,
    valueError,
    valuePathHint,
    writeSourcePath,
} from '../../../core/helpers/key-value-node.helpers';
import { KeyValueEntry, KeyValueMode } from '../../../core/models/key-value-node.model';
import { KeyValueNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { FlowService } from '../../../services/flow.service';
import { KeyValueEntryDraftsService } from '../../../services/key-value-entry-drafts.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { PickerItem } from '../../input-map/var-picker-flat.component';
import {
    buildVariablePickerItems,
    isPlainEnter,
    VariablePathPicker,
    withoutUsedPaths,
} from '../../input-map/variable-path-picker';
import { highlightVariablesHtml } from '../shared/variable-highlight-textarea/highlight-variables';
import { VariableDropdownOverlayComponent } from '../shared/variable-highlight-textarea/variable-dropdown-overlay/variable-dropdown-overlay.component';

const SUGGESTION_LIMIT = 20;
// Keys that move the caret in a key input without typing, so its placeholder may change.
const CARET_KEYS: ReadonlySet<string> = new Set(['ArrowLeft', 'ArrowRight', 'Home', 'End']);
const CANVAS_SYNC_DEBOUNCE_MS = 300;
const DUPLICATE_KEY_HINT = 'Duplicate key — use a different key';
const KEY_HELP = 'Use {variables.name} to insert a variable into the key';
const DUPLICATE_VARIABLE_HINT = 'Duplicate variable — use a different variable';
const OVERLAPPING_VARIABLE_HINT = 'Overlaps another variable — use a different variable';
const CREATE_TABLE_ACTION: SelectDropdownHeaderAction = { icon: 'plus', label: 'Create table', iconOnly: true };
const MODE_ITEMS: SelectItem<KeyValueMode>[] = [
    { name: 'Read', value: 'read' },
    { name: 'Write', value: 'write' },
    { name: 'Delete', value: 'delete' },
];
const NO_READ_NOTICE = 'You need View permission on Key-Value Tables to configure this node.';
// Names the permissions KEY_VALUE_MODE_ACTIONS lists, as the role editor calls them.
const MODE_LOCKED_NOTICE: Record<KeyValueMode, string> = {
    // Never shown: a user who can't configure read has no View, and NO_READ_NOTICE comes first.
    read: 'Changing a Read node needs View permission on Key-Value Tables.',
    write: 'Changing a Write node needs Create and Edit permission on Key-Value Tables.',
    delete: 'Changing a Delete node needs Delete permission on Key-Value Tables.',
};
// What a locked panel keeps as saved; the node name stays editable.
const LOCKABLE_CONTROLS = ['key_value_table', 'mode', 'entries'];
const KEYS_LABEL: Record<KeyValueMode, string> = {
    read: 'Keys to Read',
    write: 'Keys to Write',
    delete: 'Keys to Delete',
};

interface KeySearch {
    entryIndex: number;
    search: string;
}

interface KeySearchResult {
    entryIndex: number;
    keys: string[];
}

/** A `{` placeholder in a key, still open at the caret: where its `{` is and what is typed after it. */
interface OpenPlaceholder {
    start: number;
    text: string;
}

interface EntryFormValue {
    key: string;
    value?: string;
}

@Component({
    selector: 'app-key-value-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        SelectComponent,
        SelectDropdownComponent,
        SelectDropdownTriggerDirective,
        AppSvgIconComponent,
        TooltipComponent,
        NgTemplateOutlet,
    ],
    templateUrl: './key-value-node-panel.component.html',
    styleUrls: ['./key-value-node-panel.component.scss'],
})
export class KeyValueNodePanelComponent extends BaseSidePanel<KeyValueNodeModel> {
    private readonly tableDropdown = viewChild(SelectDropdownComponent);

    protected readonly mode = signal<KeyValueMode>('read');
    protected readonly loadingTables = signal(false);
    protected readonly lookups = signal<KeyValueEntryLookupResponse>({});
    protected readonly placeholderHints = signal<Record<number, string>>({});
    // Each key as backdrop HTML, its state path placeholders marked the way the task node marks variables.
    protected readonly keyHighlights = signal<string[]>([]);
    // The row whose key was focused last, which alone carries the key help (keyHelpFor).
    private readonly keyHelpRow = signal<AbstractControl | null>(null);
    private readonly suggestions = signal<string[]>([]);
    private readonly activeSuggestionIndex = signal(0);
    // The key input the suggestions belong to; null once they are dismissed, so a late search is dropped.
    private readonly suggestionTarget = signal<{ entryIndex: number; input: HTMLInputElement } | null>(null);
    protected readonly canReadData = computed(() => this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Read));
    // The saved mode, not the form's: a node the user may not configure keeps its mode, table and keys.
    protected readonly modeLocked = computed(() => !this.canConfigure(this.node().data.mode));
    protected readonly configurationLocked = computed(() => !this.canReadData() || this.modeLocked());
    protected readonly permissionNotice = computed<string | null>(() => {
        if (!this.canReadData()) return NO_READ_NOTICE;
        return this.modeLocked() ? MODE_LOCKED_NOTICE[this.node().data.mode] : null;
    });
    // Only the modes the user may configure; a locked select shows just the saved one.
    protected readonly modeItems = computed(() => {
        const savedMode = this.node().data.mode;
        if (this.modeLocked()) return MODE_ITEMS.filter((item) => item.value === savedMode);
        return MODE_ITEMS.filter((item) => this.canConfigure(item.value));
    });
    // The "+" next to the search; hidden without the right to create a table.
    protected readonly createTableAction = computed(() =>
        this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Create) ? CREATE_TABLE_ACTION : null
    );
    // "No table" clears the table; search filters it by its name like any other row.
    protected readonly tableItems = computed<SelectDropdownListItem<number | null>[]>(() => [
        { name: 'No table', value: null },
        ...this.keyValueTablesStorage.tables().map((table) => ({ name: table.name, value: table.id })),
    ]);
    // The form is not a signal: node() covers a re-initialized form, dirtyCheckTick its value changes.
    protected readonly selectedTableId = computed<number | null>(() => {
        this.node();
        this.dirtyCheckTick();
        return this.form?.get('key_value_table')?.value ?? null;
    });
    // [null] checks the "No table" row.
    protected readonly selectedTableValue = computed<(number | null)[]>(() => [this.selectedTableId()]);
    // Null for a table that is gone or out of reach too, which then shows the placeholder.
    protected readonly selectedTableName = computed<string | null>(() => {
        const tableId = this.selectedTableId();
        return this.keyValueTablesStorage.tables().find((table) => table.id === tableId)?.name ?? null;
    });
    protected readonly tableTriggerLabel = computed(() => {
        if (this.loadingTables()) return 'Loading tables...';
        return this.selectedTableName() ?? 'Select a table';
    });
    protected readonly keysLabel = computed(() => KEYS_LABEL[this.mode()]);
    // Leaves out names a key-value node can't use, such as `user-name` or `_private`.
    private readonly variableItems = computed(() =>
        buildVariablePickerItems(this.flowService.startNodeInitialState()).filter((item) => isStatePath(item.fullPath))
    );

    protected readonly activeColor = 'var(--accent-color)';
    protected readonly keyLimitHint = `A Key-Value node can have at most ${KEY_VALUE_MAX_KEYS} keys`;
    protected readonly keyPlaceholder = KEY_PLACEHOLDER_HINT;
    // The Input List's picker. Read rows each fill their own variable, so a row is not offered what
    // other rows fill, nor what lies inside or around it: those stay only as disabled parents of what
    // is still offered. Write rows may share a source, so each is offered every variable.
    protected readonly variablePicker = new VariablePathPicker({
        itemsFor: (rowIndex) => (this.mode() === 'read' ? this.readTargetItemsFor(rowIndex) : this.variableItems()),
        insert: (rowIndex, path) => {
            const control = this.entries.at(rowIndex).get('value');
            control?.setValue(path);
            control?.markAsDirty();
        },
        pathOf: writeSourcePath,
    });
    // The same picker for a `{variables.…` placeholder at a key's caret; any flow variable may go into a key.
    protected readonly keyVariablePicker = new VariablePathPicker({
        itemsFor: () => this.variableItems(),
        insert: (rowIndex, path, input) => this.insertIntoKeyPlaceholder(rowIndex, path, input),
        // trimStart: crew allows spaces inside the braces, as in `{ variables.user.id }`.
        pathOf: (value, input) =>
            openPlaceholderAt(value, input.selectionStart ?? value.length)?.text.trimStart() ?? '',
    });

    private readonly keyValueTablesApi = inject(KeyValueTablesApiService);
    private readonly keyValueTablesStorage = inject(KeyValueTablesStorageService);
    private readonly permissions = inject(PermissionsService);
    private readonly flowService = inject(FlowService);
    private readonly valueDrafts = inject(KeyValueEntryDraftsService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly toastService = inject(ToastService);
    private readonly dialog = inject(Dialog);
    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly injector = inject(Injector);
    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly keySearch$ = new Subject<KeySearch>();
    private suggestionOverlay: OverlayRef | null = null;
    private tablesLoad: Subscription | null = null;
    private suggestionDropdown: VariableDropdownOverlayComponent | null = null;
    // The value a row had before a switch to delete removed its value field, so switching back restores it.
    private readonly hiddenValues = new WeakMap<FormGroup, string>();

    constructor() {
        super();
        if (this.keyValueTablesStorage.tables().length === 0) {
            this.trackTablesLoad(this.keyValueTablesStorage.loadTables());
        }

        this.keySearch$
            .pipe(
                debounceTime(250),
                switchMap((search) => this.fetchKeySuggestions(search)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((result) => this.showKeySuggestions(result));

        effect(() => {
            const suggestions = this.suggestions();
            const activeIndex = this.activeSuggestionIndex();
            if (suggestions.length === 0) {
                this.closeSuggestionOverlay();
                return;
            }
            this.openSuggestionOverlay()?.updateItems(suggestions, activeIndex);
        });
        this.destroyRef.onDestroy(() => this.closeSuggestionOverlay());

        // Permissions may arrive or change after the form is built, e.g. on an org switch.
        effect(() => {
            const locked = this.configurationLocked();
            untracked(() => {
                if (!this.form) return;
                // A relock mid-edit: put back what is saved, so no edit the server would refuse is kept.
                if (locked && this.form.get('mode')?.enabled) this.restoreSavedConfiguration(this.form);
                this.applyConfigurationLock(this.form, locked);
            });
        });
    }

    /**
     * Autosave and panel close put what this returns into the flow, which is what the canvas shows.
     * (Ctrl+S goes through the base onSaveSilently(), which still refuses an invalid form, so the
     * panel stays open on it.)
     * Invalid entries go there too, so the canvas always shows the panel's mode, table and key count;
     * the flow save refuses them (hasValidKeyValueEntries). Only an invalid name is held back, as
     * in every other panel.
     */
    public override onSave(): KeyValueNodeModel | null {
        if (!this.form || this.form.controls['node_name'].invalid) return null;
        const updatedNode = this.createUpdatedNode();
        this.initialNodeSnapshot = JSON.stringify(updatedNode);
        this.notifyExternalChange();
        return updatedNode;
    }

    /**
     * The flow save writes whatever the open panel returns here. Returning null aborts the save, as
     * the schedule-trigger panel does, with a toast pointing at the highlighted fields; the flow
     * save's own check covers a node whose panel is closed. Empty rows are never invalid.
     */
    // Known limit: a locked node's disabled controls don't validate, so one with an old invalid key
    // (dev data only) passes here; the flow save's own check (hasValidKeyValueEntries) still
    // refuses it, and only a user allowed to configure the node can fix it.
    public override captureForValidation(): KeyValueNodeModel | null {
        if (!this.form) return null;
        this.form.markAllAsTouched();
        if (this.form.invalid) {
            const nodeName: string = this.form.value.node_name?.trim() || this.node().node_name;
            this.toastService.error(`Fix the highlighted fields in "${nodeName}" to save the flow.`);
            return null;
        }
        return super.captureForValidation();
    }

    protected get entries(): FormArray {
        return this.form.get('entries') as FormArray;
    }

    protected initializeForm(): FormGroup {
        const node = this.node();
        const { mode, key_value_table, entries } = node.data;
        this.mode.set(mode);
        this.lookups.set({});

        const form = this.fb.group({
            node_name: [node.node_name, this.createNodeNameValidators()],
            key_value_table: this.fb.control<number | null>(key_value_table),
            mode: this.fb.control<KeyValueMode>(mode),
            entries: this.fb.array<FormGroup>(
                entries.map((entry) => this.createEntryGroup(entry, mode)),
                keyLimitValidator
            ),
        });
        // A delete node opened again gets back the values its rows had when the panel was last open.
        const occurrences = keyOccurrences(entries.map((entry) => entry.key));
        form.controls.entries.controls.forEach((row, index) => {
            const draft = this.valueDrafts.valueFor(node.id, entries[index].key, occurrences[index]);
            if (mode === 'delete' && draft !== undefined) this.hiddenValues.set(row, draft);
        });

        // A write key or a read variable repeats because of the other rows, which its own row doesn't see change.
        const entriesArray = form.controls.entries;
        entriesArray.valueChanges.pipe(startWith(null), takeUntilDestroyed(this.destroyRef)).subscribe(() =>
            entriesArray.controls.forEach((row) => {
                row.get('key')?.updateValueAndValidity({ emitEvent: false });
                row.get('value')?.updateValueAndValidity({ emitEvent: false });
            })
        );

        form.controls.mode.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((newMode) => this.onModeChange(form, newMode ?? 'read'));

        form.valueChanges.pipe(startWith(null), takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.refreshPlaceholderHints(form);
            this.refreshKeyHighlights(form);
            this.rememberValues(form, node.id);
        });

        form.valueChanges
            .pipe(
                startWith(null),
                map(() => this.buildLookupRequest(form)),
                debounceTime(300),
                distinctUntilChanged(isSameLookupRequest),
                switchMap((request) => this.fetchLookups(request)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((lookups) => this.lookups.set(lookups));

        // The canvas badge and subtitle show mode, table and key count, and read the node from the flow,
        // so push those edits there now instead of on panel close, even while entries are invalid (onSave).
        form.valueChanges
            .pipe(
                startWith(null),
                map(() => canvasSummary(form)),
                distinctUntilChanged(),
                skip(1),
                debounceTime(CANVAS_SYNC_DEBOUNCE_MS),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.sidePanelService.triggerAutosave());

        this.applyConfigurationLock(form, untracked(this.configurationLocked));
        return form;
    }

    /** Raw values: a locked panel's disabled controls still hold what the node saves. */
    protected createUpdatedNode(): KeyValueNodeModel {
        const { node_name, mode, key_value_table } = this.form.getRawValue();
        const entryValues: EntryFormValue[] = this.entries.getRawValue();

        return {
            ...this.node(),
            node_name,
            // Entries reference flow state paths directly, for inputs and for read results alike.
            input_map: {},
            output_variable_path: null,
            data: {
                key_value_table: key_value_table ?? null,
                mode,
                entries: entryValues
                    .filter((entryValue) => !isEmptyEntry(entryValue))
                    .map(({ key, value }) => normalizeEntry({ key, value: value?.trim() }, mode)),
            },
        };
    }

    protected onTableSelectionChange(values: unknown[]): void {
        this.selectTable((values[0] as number | undefined) ?? null);
    }

    /** Creates a table without leaving the flow and selects it. */
    protected openCreateTable(): void {
        this.tableDropdown()?.close();
        this.dialog
            .open<KeyValueTable | null>(KeyValueTableDialogComponent, { width: '480px' })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((table) => {
                if (!table) return;
                this.toastService.success(`Table "${table.name}" created`);
                this.selectTable(table.id);
                // Through the shared cache, so the Files page and other panels list the new table too;
                // a reload, as a load already in flight may have started before the create.
                this.trackTablesLoad(this.keyValueTablesStorage.reloadTables());
            });
    }

    /** Every row counts here, empty or not, so "Add key" stops where the saved keys would. */
    protected get atKeyLimit(): boolean {
        return this.entries.length >= KEY_VALUE_MAX_KEYS;
    }

    /** Focuses the new row's key, so its key help shows under it as the user starts typing. */
    protected addEntry(): void {
        if (this.atKeyLimit) return;
        this.entries.push(this.createNewEntryGroup());
        const newIndex = this.entries.length - 1;
        afterNextRender(() => this.keyInputOf(newIndex)?.focus(), { injector: this.injector });
    }

    protected removeEntry(index: number): void {
        this.entries.removeAt(index);
    }

    /**
     * Inside a `{` placeholder the variable snippets apply. Stored keys are static text, so a key
     * with braces has no stored key to suggest.
     */
    protected onKeyInput(entryIndex: number, event: Event): void {
        const input = event.target as HTMLInputElement;
        this.keyVariablePicker.onInput(entryIndex, event);
        if (input.value.includes('{')) {
            this.dismissSuggestions();
            return;
        }
        this.suggestionTarget.set({ entryIndex, input });
        this.keySearch$.next({ entryIndex, search: input.value });
    }

    /** An open list takes the keys it uses first, Enter included; Enter then moves on (moveOnEnter). */
    protected onKeyKeydown(entryIndex: number, event: KeyboardEvent): void {
        this.keyVariablePicker.onKeydown(entryIndex, event);
        if (!event.defaultPrevented) this.onSuggestionKeydown(event);
        this.moveOnEnter(entryIndex, event);
    }

    /** The caret moved without typing, so the placeholder it is in, if any, may be another one. */
    protected onKeyCaretMove(entryIndex: number, event: Event): void {
        if (event instanceof KeyboardEvent && !CARET_KEYS.has(event.key)) return;
        this.keyVariablePicker.onCaretMove(entryIndex, event);
    }

    protected onKeyFocus(entryIndex: number): void {
        this.keyHelpRow.set(this.entries.at(entryIndex));
    }

    protected onKeyBlur(entryIndex: number, event: FocusEvent): void {
        this.keyVariablePicker.onBlur(entryIndex, event);
        this.dismissSuggestions();
    }

    protected onValueKeydown(entryIndex: number, event: KeyboardEvent): void {
        this.variablePicker.onKeydown(entryIndex, event);
        this.moveOnEnter(entryIndex, event);
    }

    protected isKeyListOpen(entryIndex: number): boolean {
        const suggestionsOpen = this.suggestionTarget()?.entryIndex === entryIndex && this.suggestions().length > 0;
        return suggestionsOpen || this.keyVariablePicker.isOpenFor(entryIndex);
    }

    protected isDuplicateKey(index: number): boolean {
        return this.entries.at(index).get('key')?.hasError('duplicateKey') ?? false;
    }

    protected keyHintFor(index: number): string | null {
        return this.isDuplicateKey(index) ? DUPLICATE_KEY_HINT : null;
    }

    /** A read target that another row's target repeats, or lies inside or around. */
    protected isConflictingVariable(index: number): boolean {
        const value = this.entries.at(index).get('value');
        return (value?.hasError('duplicateVariable') || value?.hasError('overlappingVariable')) ?? false;
    }

    /** The untouched `variables.` prefill is not an error yet; the user is about to type the rest. */
    protected valueHintFor(index: number): string | null {
        const value = this.entries.at(index).get('value');
        if (value?.hasError('duplicateVariable')) return DUPLICATE_VARIABLE_HINT;
        if (value?.hasError('overlappingVariable')) return OVERLAPPING_VARIABLE_HINT;
        if (!value?.hasError('pattern')) return null;
        if (value.value === VALUE_PREFILL && value.pristine && value.untouched) return null;
        return valuePathHint(value.value, this.mode());
    }

    protected existenceHintFor(index: number): string | null {
        const key: string = this.entries.at(index).value.key ?? '';
        return existenceHint(this.mode(), this.lookups()[key]);
    }

    /**
     * How to put a variable into a key, under the key focused last only, so a long list carries one
     * line. It stays after blur, so rows below don't jump under a click. Any hint or error the key
     * shows takes its place.
     */
    protected keyHelpFor(index: number): string | null {
        const row = this.entries.at(index);
        if (row !== this.keyHelpRow() || this.configurationLocked()) return null;
        const key = row.get('key');
        if (key === null || (key.invalid && key.touched)) return null;
        const shownHint = this.placeholderHints()[index] ?? this.keyHintFor(index) ?? this.existenceHintFor(index);
        return shownHint === null ? KEY_HELP : null;
    }

    /**
     * Keeps every row, so each keeps its own value whatever happens to the keys: delete only takes
     * the value field away, and leaving delete puts it back with the value it had. The form emits
     * the new value once this returns, as the mode control's change reaches it.
     */
    private onModeChange(form: FormGroup, newMode: KeyValueMode): void {
        if (newMode === this.mode()) return;
        this.mode.set(newMode);

        const rows = (form.get('entries') as FormArray<FormGroup>).controls;
        rows.forEach((row) => {
            const value = row.get('value');
            if (newMode === 'delete') {
                if (value) this.hiddenValues.set(row, value.value ?? '');
                row.removeControl('value', { emitEvent: false });
            } else if (value) {
                value.setValidators(unlessEmptyEntry(...valueValidators(newMode)));
            } else {
                const restored = this.hiddenValues.get(row) ?? VALUE_PREFILL;
                row.addControl('value', this.fb.control(restored, unlessEmptyEntry(...valueValidators(newMode))), {
                    emitEvent: false,
                });
            }
            row.get('key')?.setValidators(unlessEmptyEntry(...keyValidators(newMode)));
        });
        // After every row has its validators, as a write key's or read variable's duplicate check reads the others.
        rows.forEach((row) =>
            Object.values(row.controls).forEach((control) => control.updateValueAndValidity({ emitEvent: false }))
        );
        this.notifyExternalChange();
    }

    /** What reopening the panel restores: each row's value, visible or hidden by delete. */
    private rememberValues(form: FormGroup, nodeId: string): void {
        const rows = (form.get('entries') as FormArray<FormGroup>).controls;
        this.valueDrafts.remember(
            nodeId,
            rows.map((row) => ({
                key: row.get('key')?.value ?? '',
                value: row.get('value')?.value ?? this.hiddenValues.get(row),
            }))
        );
    }

    /**
     * Disables or enables what a locked panel keeps; the node name stays editable. See
     * captureForValidation for what a locked node skips.
     */
    private applyConfigurationLock(form: FormGroup, locked: boolean): void {
        LOCKABLE_CONTROLS.forEach((name) => {
            const control = form.get(name);
            if (!control || control.disabled === locked) return;
            if (locked) control.disable({ emitEvent: false });
            else control.enable({ emitEvent: false });
        });
        this.notifyExternalChange();
    }

    /**
     * The node's saved mode, table and keys, without the form emitting (so nothing autosaves). Only
     * for a relock: a fresh form already holds them, with the values a delete node keeps hidden.
     */
    private restoreSavedConfiguration(form: FormGroup): void {
        const { mode, key_value_table, entries } = this.node().data;
        this.mode.set(mode);
        form.get('mode')?.setValue(mode, { emitEvent: false });
        form.get('key_value_table')?.setValue(key_value_table, { emitEvent: false });
        const rows = form.get('entries') as FormArray;
        rows.clear({ emitEvent: false });
        entries.forEach((entry) => rows.push(this.createEntryGroup(entry, mode), { emitEvent: false }));
        this.refreshPlaceholderHints(form);
        this.refreshKeyHighlights(form);
    }

    private canConfigure(mode: KeyValueMode): boolean {
        return canConfigureMode(mode, (action) => this.permissions.can(ResourceCode.KeyValueTables, action));
    }

    private selectTable(tableId: number | null): void {
        const control = this.form.controls['key_value_table'];
        control.setValue(tableId);
        control.markAsDirty();
        control.markAsTouched();
    }

    // A failed load keeps the list it had; the panel still works with it. A newer load replaces the
    // one running, so the older one's end can't stop the spinner while the newer one still runs.
    private trackTablesLoad(load$: Observable<KeyValueTable[]>): void {
        this.tablesLoad?.unsubscribe();
        this.loadingTables.set(true);
        this.tablesLoad = load$
            .pipe(
                finalize(() => this.loadingTables.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({ error: () => undefined });
    }

    private readTargetItemsFor(rowIndex: number): PickerItem[] {
        // Only finished targets: a half-typed `variables.user.` takes nothing away yet.
        const otherTargets = this.entries.controls
            .filter((_row, index) => index !== rowIndex)
            .map((row) => validReadTarget(row.get('value')?.value ?? ''))
            .filter((target): target is string => target !== null);
        const items = this.variableItems();
        const unusable = items
            .map((item) => item.fullPath)
            .filter((path) => otherTargets.some((target) => path === target || isNestedPath(path, target)));
        return withoutUsedPaths(items, new Set(unusable));
    }

    /**
     * Enter goes through the fields in the order the row shows them (read shows `variables.x = key`):
     * to the row's next field, and from its last field to a new row below, prefilled as by Add key.
     * At the key limit it adds none. A list open under the field has taken Enter by then if it picked.
     */
    private moveOnEnter(entryIndex: number, event: KeyboardEvent): void {
        if (event.isComposing || !isPlainEnter(event) || event.defaultPrevented) return;
        event.preventDefault();
        const fields = this.rowFields(entryIndex);
        const nextField = fields[fields.indexOf(event.target as HTMLInputElement) + 1];
        if (nextField) {
            nextField.focus();
            return;
        }
        if (this.atKeyLimit) return;
        this.entries.insert(entryIndex + 1, this.createNewEntryGroup());
        afterNextRender(() => this.rowFields(entryIndex + 1)[0]?.focus(), { injector: this.injector });
    }

    private keyInputOf(entryIndex: number): HTMLInputElement | null {
        return this.rowFields(entryIndex).find((field) => field.classList.contains('key-input')) ?? null;
    }

    /** A row's inputs in the order they show. */
    private rowFields(entryIndex: number): HTMLInputElement[] {
        // A DOM query, not viewChildren: the inputs sit in ng-templates stamped in a per-mode order,
        // which a query list does not keep by row, and a new row only exists after the next render.
        const row = this.host.nativeElement.querySelectorAll('.entry-row')[entryIndex];
        return row ? Array.from(row.querySelectorAll<HTMLInputElement>('input.entry-input')) : [];
    }

    /** Puts a picked path into the placeholder at the key's caret, closed with `}` unless it is, the caret after it. */
    private insertIntoKeyPlaceholder(entryIndex: number, path: string, input: HTMLInputElement): void {
        const control = this.entries.at(entryIndex).get('key');
        const key: string = control?.value ?? '';
        const caret = input.selectionStart ?? key.length;
        const placeholder = openPlaceholderAt(key, caret);
        if (!control || placeholder === null) return;
        // What is typed on up to the placeholder's `}` belongs to it and is replaced too.
        const rest = key.slice(caret);
        const nextBrace = rest.search(/[{}]/);
        const afterPlaceholder = rest[nextBrace] === '}' ? rest.slice(nextBrace + 1) : rest;
        const throughPlaceholder = `${key.slice(0, placeholder.start + 1)}${path}}`;
        control.setValue(throughPlaceholder + afterPlaceholder);
        control.markAsDirty();
        input.setSelectionRange(throughPlaceholder.length, throughPlaceholder.length);
    }

    private createNewEntryGroup(): FormGroup {
        return this.createEntryGroup({ key: '', value: VALUE_PREFILL }, this.mode());
    }

    private createEntryGroup(entry: KeyValueEntry, mode: KeyValueMode): FormGroup {
        const group = this.fb.group(this.entryControls(entry, mode));
        // Each field's validity depends on whether the whole row is empty, so typing in one field
        // re-checks the others. emitEvent: false keeps this from re-triggering itself.
        const revalidateFields = (): void =>
            Object.values(group.controls).forEach((control) => control.updateValueAndValidity({ emitEvent: false }));
        revalidateFields();
        group.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(revalidateFields);
        return group;
    }

    private entryControls(entry: KeyValueEntry, mode: KeyValueMode): Record<string, unknown[]> {
        const key = [entry.key, unlessEmptyEntry(...keyValidators(mode))];
        if (mode === 'delete') return { key };
        return { key, value: ['value' in entry ? entry.value : '', unlessEmptyEntry(...valueValidators(mode))] };
    }

    private onSuggestionKeydown(event: KeyboardEvent): void {
        const count = this.suggestions().length;
        if (count === 0) return;
        switch (event.key) {
            case 'ArrowDown':
            case 'ArrowUp': {
                event.preventDefault();
                const step = event.key === 'ArrowDown' ? 1 : -1;
                this.activeSuggestionIndex.update((index) => (index + step + count) % count);
                break;
            }
            case 'Enter':
                event.preventDefault();
                this.pickSuggestion(this.suggestions()[this.activeSuggestionIndex()]);
                break;
            case 'Escape':
                // Keeps the shortcut listener from closing the whole panel.
                event.preventDefault();
                event.stopPropagation();
                this.dismissSuggestions();
                break;
        }
    }

    private pickSuggestion(suggestion: string): void {
        const target = this.suggestionTarget();
        if (target === null) return;
        const control = this.entries.at(target.entryIndex).get('key');
        control?.setValue(suggestion);
        control?.markAsDirty();
        this.dismissSuggestions();
    }

    private dismissSuggestions(): void {
        this.suggestionTarget.set(null);
        this.suggestions.set([]);
    }

    private showKeySuggestions(result: KeySearchResult): void {
        if (this.suggestionTarget()?.entryIndex !== result.entryIndex) return;
        this.activeSuggestionIndex.set(0);
        this.suggestions.set(result.keys);
    }

    private openSuggestionOverlay(): VariableDropdownOverlayComponent | null {
        if (this.suggestionDropdown !== null) return this.suggestionDropdown;
        const target = untracked(this.suggestionTarget);
        if (target === null) return null;

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(target.input)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(true)
            .withViewportMargin(8)
            .withFlexibleDimensions(false);
        this.suggestionOverlay = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
        });
        const dropdown = this.suggestionOverlay.attach(
            new ComponentPortal(VariableDropdownOverlayComponent, this.viewContainerRef)
        ).instance;
        // Disposing the overlay destroys the dropdown, which ends these subscriptions.
        dropdown.itemSelected.subscribe((suggestion) => this.pickSuggestion(suggestion));
        dropdown.activeIndexChange.subscribe((index) => this.activeSuggestionIndex.set(index));
        this.suggestionDropdown = dropdown;
        return dropdown;
    }

    private closeSuggestionOverlay(): void {
        this.suggestionOverlay?.dispose();
        this.suggestionOverlay = null;
        this.suggestionDropdown = null;
    }

    private refreshPlaceholderHints(form: FormGroup): void {
        const hints: Record<number, string> = {};
        (form.get('entries') as FormArray).controls.forEach((entry, index) => {
            const hint = keyTemplateHint(entry.value.key ?? '');
            if (hint !== null) hints[index] = hint;
        });
        this.placeholderHints.set(hints);
    }

    private refreshKeyHighlights(form: FormGroup): void {
        const keys: string[] = (form.get('entries') as FormArray).controls.map((entry) => entry.value.key ?? '');
        this.keyHighlights.set(keys.map((key) => highlightVariablesHtml(key, isStatePath)));
    }

    private buildLookupRequest(form: FormGroup): LookupRequest {
        const keys = (form.get('entries') as FormArray).controls.map((entry) => (entry.value.key as string) ?? '');
        const staticKeys = keys.filter(
            (key) => key !== '' && key.length <= KEY_VALUE_KEY_MAX_LENGTH && isStaticKey(key)
        );
        return { table: form.get('key_value_table')?.value ?? null, staticKeys: Array.from(new Set(staticKeys)) };
    }

    private fetchLookups(request: LookupRequest): Observable<KeyValueEntryLookupResponse> {
        if (request.table === null || !this.canReadData() || request.staticKeys.length === 0) {
            return of({});
        }
        // Existence is advisory; a failed lookup just hides the hints.
        return this.keyValueTablesApi.lookupEntries(request.table, request.staticKeys).pipe(catchError(() => of({})));
    }

    private fetchKeySuggestions({ entryIndex, search }: KeySearch): Observable<KeySearchResult> {
        const table: number | null = this.form.get('key_value_table')?.value ?? null;
        if (table === null || !this.canReadData()) {
            return of({ entryIndex, keys: [] });
        }
        return this.keyValueTablesApi.getEntries({ table, search, limit: SUGGESTION_LIMIT, offset: 0 }).pipe(
            map((page) => ({
                entryIndex,
                keys: page.results.map((entry) => entry.key).filter((key) => key !== search),
            })),
            catchError(() => of({ entryIndex, keys: [] }))
        );
    }
}

/** The `{` placeholder before the caret that no `}` has closed yet, or null. */
function openPlaceholderAt(key: string, caret: number): OpenPlaceholder | null {
    const start = caret === 0 ? -1 : key.lastIndexOf('{', caret - 1);
    if (start === -1) return null;
    const text = key.slice(start + 1, caret);
    return text.includes('}') ? null : { start, text };
}

/** An empty row is left out of the save, so its fields are not validated. */
function unlessEmptyEntry(...validators: ValidatorFn[]): ValidatorFn {
    const validate = Validators.compose(validators);
    return (control) => {
        const row = control.parent;
        if (validate === null || (row !== null && isEmptyEntry(row.getRawValue()))) return null;
        return validate(control);
    };
}

// The rules live in the helpers, shared with the flow save; these only report them to the form.
function keyValidator(control: AbstractControl<string | null>): ValidationErrors | null {
    const error = keyError(control.value ?? '');
    return error === null ? null : { [error]: true };
}

function keyValidators(mode: KeyValueMode): ValidatorFn[] {
    return mode === 'write' ? [keyValidator, uniqueWriteKeyValidator] : [keyValidator];
}

function valueValidators(mode: KeyValueMode): ValidatorFn[] {
    return mode === 'read' ? [valueValidator(mode), uniqueReadTargetValidator] : [valueValidator(mode)];
}

function valueValidator(mode: KeyValueMode): ValidatorFn {
    return (control: AbstractControl<string | null>) => {
        const error = valueError(control.value ?? '', mode);
        return error === null ? null : { [error]: true };
    };
}

/** Every row that is saved, from one of its fields. Empty rows are not saved, so they repeat nothing. */
function savedEntries(control: AbstractControl): EntryFormValue[] {
    const rows = control.parent?.parent;
    if (!(rows instanceof FormArray)) return [];
    return rows.controls.map((row): EntryFormValue => row.getRawValue()).filter((row) => !isEmptyEntry(row));
}

function uniqueWriteKeyValidator(control: AbstractControl<string | null>): ValidationErrors | null {
    const duplicates = duplicateWriteKeys(savedEntries(control).map((row) => row.key ?? ''));
    return duplicates.has(control.value ?? '') ? { duplicateKey: true } : null;
}

function uniqueReadTargetValidator(control: AbstractControl<string | null>): ValidationErrors | null {
    const conflict = readTargetConflict(
        control.value ?? '',
        savedEntries(control).map((row) => row.value ?? '')
    );
    if (conflict === 'duplicate') return { duplicateVariable: true };
    return conflict === 'overlap' ? { overlappingVariable: true } : null;
}

/** The flow save refuses more saved keys than the backend takes in one node; empty rows are not saved. */
function keyLimitValidator(control: AbstractControl): ValidationErrors | null {
    if (!(control instanceof FormArray)) return null;
    const rows: EntryFormValue[] = control.getRawValue();
    return rows.filter((row) => !isEmptyEntry(row)).length > KEY_VALUE_MAX_KEYS ? { keyLimit: true } : null;
}

function canvasSummary(form: FormGroup): string {
    const { mode, key_value_table } = form.getRawValue();
    const entries: EntryFormValue[] = (form.get('entries') as FormArray).getRawValue();
    // Empty rows are not saved, so they don't count toward the canvas key count.
    const keyCount = entries.filter((entry) => !isEmptyEntry(entry)).length;
    return JSON.stringify([mode, key_value_table, keyCount]);
}

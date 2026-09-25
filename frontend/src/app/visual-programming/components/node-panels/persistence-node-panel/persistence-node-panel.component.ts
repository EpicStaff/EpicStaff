import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { Component, computed, effect, inject, signal, untracked, ViewContainerRef } from '@angular/core';
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
    SelectItem,
    TooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import {
    catchError,
    debounceTime,
    distinctUntilChanged,
    map,
    Observable,
    of,
    skip,
    startWith,
    Subject,
    switchMap,
} from 'rxjs';

import { PersistenceEntryLookupResponse } from '../../../../features/persistent-data/models/persistence-table.model';
import { PersistenceTablesApiService } from '../../../../features/persistent-data/services/persistence-tables-api.service';
import { PersistenceTablesStorageService } from '../../../../features/persistent-data/services/persistence-tables-storage.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import {
    duplicateReadTargets,
    existenceHint,
    flowVariablePaths,
    isEmptyEntry,
    isSameLookupRequest,
    isStaticKey,
    keyError,
    keyTemplateHint,
    LookupRequest,
    normalizeEntry,
    PERSISTENCE_KEY_MAX_LENGTH,
    reshapeEntriesForMode,
    VALUE_PREFILL,
    valueError,
    valuePathHint,
} from '../../../core/helpers/persistence-node.helpers';
import { PersistenceNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { PersistenceEntry, PersistenceMode } from '../../../core/models/persistence-node.model';
import { FlowService } from '../../../services/flow.service';
import { PersistenceValueDraftsService } from '../../../services/persistence-value-drafts.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { VariableDropdownOverlayComponent } from '../shared/variable-highlight-textarea/variable-dropdown-overlay/variable-dropdown-overlay.component';

// For stored keys and for flow variables alike.
const SUGGESTION_LIMIT = 20;
const CANVAS_SYNC_DEBOUNCE_MS = 300;
const DUPLICATE_TARGET_HINT = 'Use a different variable for each key';
const KEYS_LABEL: Record<PersistenceMode, string> = {
    read: 'Keys to Read',
    write: 'Keys to Write',
    delete: 'Keys to Delete',
};

/** The row input a suggestion list belongs to. */
type SuggestionField = 'key' | 'value';

interface KeySearch {
    entryIndex: number;
    search: string;
}

interface KeySearchResult {
    entryIndex: number;
    keys: string[];
}

interface EntryFormValue {
    key: string;
    value?: string;
}

@Component({
    selector: 'app-persistence-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        SelectComponent,
        AppSvgIconComponent,
        TooltipComponent,
    ],
    templateUrl: './persistence-node-panel.component.html',
    styleUrls: ['./persistence-node-panel.component.scss'],
})
export class PersistenceNodePanelComponent extends BaseSidePanel<PersistenceNodeModel> {
    protected readonly mode = signal<PersistenceMode>('read');
    protected readonly loadingTables = signal(false);
    protected readonly lookups = signal<PersistenceEntryLookupResponse>({});
    protected readonly placeholderHints = signal<Record<number, string>>({});
    private readonly suggestions = signal<string[]>([]);
    private readonly activeSuggestionIndex = signal(0);
    // The input the suggestions belong to; null once they are dismissed, so a late key search is dropped.
    private readonly suggestionTarget = signal<{
        entryIndex: number;
        field: SuggestionField;
        input: HTMLInputElement;
    } | null>(null);
    protected readonly canReadData = computed(() => this.permissions.can(ResourceCode.PersistentData, ActionCode.Read));
    protected readonly tableItems = computed<SelectItem<number | null>[]>(() => [
        { name: 'Select a table', value: null },
        ...this.persistenceTablesStorage.tables().map((table) => ({ name: table.name, value: table.id })),
    ]);
    protected readonly keysLabel = computed(() => KEYS_LABEL[this.mode()]);
    private readonly variablePaths = computed(() => flowVariablePaths(this.flowService.startNodeInitialState()));

    protected readonly activeColor = 'var(--accent-color)';
    protected readonly modeItems: SelectItem<PersistenceMode>[] = [
        { name: 'Read', value: 'read' },
        { name: 'Write', value: 'write' },
        { name: 'Delete', value: 'delete' },
    ];

    private readonly persistenceTablesApi = inject(PersistenceTablesApiService);
    private readonly persistenceTablesStorage = inject(PersistenceTablesStorageService);
    private readonly permissions = inject(PermissionsService);
    private readonly flowService = inject(FlowService);
    private readonly valueDrafts = inject(PersistenceValueDraftsService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly toastService = inject(ToastService);
    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly keySearch$ = new Subject<KeySearch>();
    private suggestionOverlay: OverlayRef | null = null;
    private suggestionDropdown: VariableDropdownOverlayComponent | null = null;

    constructor() {
        super();
        if (this.persistenceTablesStorage.tables().length === 0) {
            this.loadingTables.set(true);
            this.persistenceTablesStorage
                .loadTables()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => this.loadingTables.set(false),
                    error: () => this.loadingTables.set(false),
                });
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
    }

    /**
     * Autosave and panel close put what this returns into the flow, which is what the canvas shows.
     * (Ctrl+S goes through the base onSaveSilently(), which still refuses an invalid form, so the
     * panel stays open on it.)
     * Invalid entries go there too, so the canvas always shows the panel's mode, table and key count;
     * the flow save refuses them (hasValidPersistenceEntries). Only an invalid name is held back, as
     * in every other panel.
     */
    public override onSave(): PersistenceNodeModel | null {
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
    public override captureForValidation(): PersistenceNodeModel | null {
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
        const { mode, persistence_table, entries } = node.data;
        this.mode.set(mode);
        this.lookups.set({});

        const form = this.fb.group({
            node_name: [node.node_name, this.createNodeNameValidators()],
            persistence_table: this.fb.control<number | null>(persistence_table),
            mode: this.fb.control<PersistenceMode>(mode),
            entries: this.fb.array<FormGroup>(entries.map((entry) => this.createEntryGroup(entry, mode))),
        });

        // A read target's validity depends on the other rows' targets, which its own row doesn't see change.
        const entriesArray = form.controls.entries;
        entriesArray.valueChanges
            .pipe(startWith(null), takeUntilDestroyed(this.destroyRef))
            .subscribe(() =>
                entriesArray.controls.forEach((row) => row.get('value')?.updateValueAndValidity({ emitEvent: false }))
            );

        form.controls.mode.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((newMode) => this.onModeChange(form, newMode ?? 'read'));

        form.valueChanges
            .pipe(startWith(null), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshPlaceholderHints(form));

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

        return form;
    }

    protected createUpdatedNode(): PersistenceNodeModel {
        const mode: PersistenceMode = this.form.value.mode;
        const entryValues: EntryFormValue[] = this.entries.getRawValue();

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            // Entries reference flow state paths directly, for inputs and for read results alike.
            input_map: {},
            output_variable_path: null,
            data: {
                persistence_table: this.form.value.persistence_table ?? null,
                mode,
                entries: entryValues
                    .filter((entryValue) => !isEmptyEntry(entryValue))
                    .map(({ key, value }) => normalizeEntry({ key, value: value?.trim() }, mode)),
            },
        };
    }

    protected addEntry(): void {
        this.entries.push(this.createEntryGroup({ key: '', value: VALUE_PREFILL }, this.mode()));
    }

    protected removeEntry(index: number): void {
        this.entries.removeAt(index);
    }

    protected onKeyInput(entryIndex: number, event: Event): void {
        const input = event.target as HTMLInputElement;
        this.suggestionTarget.set({ entryIndex, field: 'key', input });
        this.keySearch$.next({ entryIndex, search: input.value });
    }

    /** Suggests the flow's variables, taken from the start node's initial state. */
    protected onValueInput(entryIndex: number, event: Event): void {
        const input = event.target as HTMLInputElement;
        const typed = input.value.trim();
        this.suggestionTarget.set({ entryIndex, field: 'value', input });
        this.activeSuggestionIndex.set(0);
        this.suggestions.set(
            this.variablePaths()
                .filter((path) => path !== typed && path.toLowerCase().includes(typed.toLowerCase()))
                .slice(0, SUGGESTION_LIMIT)
        );
    }

    protected onSuggestionKeydown(event: KeyboardEvent): void {
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

    protected onSuggestionBlur(): void {
        this.dismissSuggestions();
    }

    protected isSuggestionListOpen(entryIndex: number, field: SuggestionField): boolean {
        const target = this.suggestionTarget();
        return target?.entryIndex === entryIndex && target.field === field && this.suggestions().length > 0;
    }

    /** The untouched `variables.` prefill is not an error yet; the user is about to type the rest. */
    protected valueHintFor(index: number): string | null {
        const value = this.entries.at(index).get('value');
        if (!value) return null;
        if (value.hasError('pattern')) {
            if (value.value === VALUE_PREFILL && value.pristine && value.untouched) return null;
            return valuePathHint(value.value, this.mode());
        }
        return value.hasError('duplicateTarget') ? DUPLICATE_TARGET_HINT : null;
    }

    protected existenceHintFor(index: number): string | null {
        const key: string = this.entries.at(index).value.key ?? '';
        return existenceHint(this.mode(), this.lookups()[key]);
    }

    private onModeChange(form: FormGroup, newMode: PersistenceMode): void {
        if (newMode === this.mode()) return;
        this.mode.set(newMode);

        const entriesArray = form.get('entries') as FormArray;
        const rows: EntryFormValue[] = entriesArray.getRawValue();
        const nodeId = this.node().id;
        this.valueDrafts.remember(nodeId, rows);
        const reshaped = reshapeEntriesForMode(rows, newMode, (key) => this.valueDrafts.valueFor(nodeId, key));
        entriesArray.clear();
        reshaped.forEach((entry) => entriesArray.push(this.createEntryGroup(entry, newMode)));
        this.notifyExternalChange();
    }

    private createEntryGroup(entry: PersistenceEntry, mode: PersistenceMode): FormGroup {
        const group = this.fb.group(this.entryControls(entry, mode));
        // Each field's validity depends on whether the whole row is empty, so typing in one field
        // re-checks the others. emitEvent: false keeps this from re-triggering itself.
        const revalidateFields = (): void =>
            Object.values(group.controls).forEach((control) => control.updateValueAndValidity({ emitEvent: false }));
        revalidateFields();
        group.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(revalidateFields);
        return group;
    }

    private entryControls(entry: PersistenceEntry, mode: PersistenceMode): Record<string, unknown[]> {
        const key = [entry.key, unlessEmptyEntry(keyValidator)];
        if (mode === 'delete') return { key };
        const valueValidators: ValidatorFn[] = [valueValidator(mode)];
        if (mode === 'read') valueValidators.push(uniqueTargetValidator);
        return { key, value: ['value' in entry ? entry.value : '', unlessEmptyEntry(...valueValidators)] };
    }

    private pickSuggestion(suggestion: string): void {
        const target = this.suggestionTarget();
        if (target === null) return;
        const control = this.entries.at(target.entryIndex).get(target.field);
        control?.setValue(suggestion);
        control?.markAsDirty();
        this.dismissSuggestions();
    }

    private dismissSuggestions(): void {
        this.suggestionTarget.set(null);
        this.suggestions.set([]);
    }

    private showKeySuggestions(result: KeySearchResult): void {
        const target = this.suggestionTarget();
        if (target?.entryIndex !== result.entryIndex || target.field !== 'key') return;
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

    private buildLookupRequest(form: FormGroup): LookupRequest {
        const keys = (form.get('entries') as FormArray).controls.map((entry) => (entry.value.key as string) ?? '');
        const staticKeys = keys.filter(
            (key) => key !== '' && key.length <= PERSISTENCE_KEY_MAX_LENGTH && isStaticKey(key)
        );
        return { table: form.get('persistence_table')?.value ?? null, staticKeys: Array.from(new Set(staticKeys)) };
    }

    private fetchLookups(request: LookupRequest): Observable<PersistenceEntryLookupResponse> {
        if (request.table === null || !this.canReadData() || request.staticKeys.length === 0) {
            return of({});
        }
        // Existence is advisory; a failed lookup just hides the hints.
        return this.persistenceTablesApi
            .lookupEntries(request.table, request.staticKeys)
            .pipe(catchError(() => of({})));
    }

    private fetchKeySuggestions({ entryIndex, search }: KeySearch): Observable<KeySearchResult> {
        const table: number | null = this.form.get('persistence_table')?.value ?? null;
        // Stored keys are static text, so a key built from placeholders has nothing to match.
        if (table === null || !this.canReadData() || search.includes('{')) {
            return of({ entryIndex, keys: [] });
        }
        return this.persistenceTablesApi.getEntries({ table, search, limit: SUGGESTION_LIMIT, offset: 0 }).pipe(
            map((page) => ({
                entryIndex,
                keys: page.results.map((entry) => entry.key).filter((key) => key !== search),
            })),
            catchError(() => of({ entryIndex, keys: [] }))
        );
    }
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

function valueValidator(mode: PersistenceMode): ValidatorFn {
    return (control: AbstractControl<string | null>) => {
        const error = valueError(control.value ?? '', mode);
        return error === null ? null : { [error]: true };
    };
}

// Empty rows are not saved, so they share nothing.
function uniqueTargetValidator(control: AbstractControl<string | null>): ValidationErrors | null {
    const rows = control.parent?.parent;
    if (!(rows instanceof FormArray)) return null;
    const values: string[] = rows.controls
        .map((row) => row.getRawValue())
        .filter((row) => !isEmptyEntry(row))
        .map((row) => row.value ?? '');
    return duplicateReadTargets(values).has((control.value ?? '').trim()) ? { duplicateTarget: true } : null;
}

function canvasSummary(form: FormGroup): string {
    const { mode, persistence_table } = form.getRawValue();
    const entries: EntryFormValue[] = (form.get('entries') as FormArray).getRawValue();
    // Empty rows are not saved, so they don't count toward the canvas key count.
    const keyCount = entries.filter((entry) => !isEmptyEntry(entry)).length;
    return JSON.stringify([mode, persistence_table, keyCount]);
}

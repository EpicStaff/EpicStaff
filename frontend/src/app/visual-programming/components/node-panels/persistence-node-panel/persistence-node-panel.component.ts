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
import {
    ExistenceBadge,
    existenceBadge,
    isEmptyEntry,
    isSameLookupRequest,
    isStatePath,
    isStaticKey,
    keyTemplateHint,
    LookupRequest,
    normalizeEntry,
    parseDefaultValue,
    reshapeEntriesForMode,
    WRITE_VALUE_PREFILL,
    writeValueHint,
} from '../../../core/helpers/persistence-node.helpers';
import { PersistenceNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { PersistenceEntry, PersistenceMode } from '../../../core/models/persistence-node.model';
import { SidePanelService } from '../../../services/side-panel.service';
import { VariableDropdownOverlayComponent } from '../shared/variable-highlight-textarea/variable-dropdown-overlay/variable-dropdown-overlay.component';

// Mirrors MAX_KEY_LENGTH in tables/constants/persistence_constants.py.
const PERSISTENCE_KEY_MAX_LENGTH = 512;
const KEY_SUGGESTION_LIMIT = 20;
const CANVAS_SYNC_DEBOUNCE_MS = 300;

interface KeySearch {
    entryIndex: number;
    search: string;
}

interface KeySearchResult {
    entryIndex: number;
    keys: string[];
}

interface EntryFormValue {
    alias?: string;
    key: string;
    value?: string;
    default?: string;
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
    private readonly keySuggestions = signal<string[]>([]);
    private readonly activeSuggestionIndex = signal(0);
    // The key input the suggestions belong to; null once they are dismissed, so a late response is dropped.
    private readonly suggestionTarget = signal<{ entryIndex: number; input: HTMLInputElement } | null>(null);
    protected readonly canReadData = computed(() => this.permissions.can(ResourceCode.PersistentData, ActionCode.Read));
    protected readonly tableItems = computed<SelectItem<number | null>[]>(() => [
        { name: 'Select a table', value: null },
        ...this.persistenceTablesStorage.tables().map((table) => ({ name: table.name, value: table.id })),
    ]);

    protected readonly activeColor = 'var(--accent-color)';
    protected readonly modeItems: SelectItem<PersistenceMode>[] = [
        { name: 'Read', value: 'read' },
        { name: 'Write', value: 'write' },
        { name: 'Delete', value: 'delete' },
    ];

    private readonly persistenceTablesApi = inject(PersistenceTablesApiService);
    private readonly persistenceTablesStorage = inject(PersistenceTablesStorageService);
    private readonly permissions = inject(PermissionsService);
    private readonly sidePanelService = inject(SidePanelService);
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
            const suggestions = this.keySuggestions();
            const activeIndex = this.activeSuggestionIndex();
            if (suggestions.length === 0) {
                this.closeSuggestionOverlay();
                return;
            }
            this.openSuggestionOverlay()?.updateItems(suggestions, activeIndex);
        });
        this.destroyRef.onDestroy(() => this.closeSuggestionOverlay());
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
            output_variable_path: [node.output_variable_path ?? ''],
        });

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
        // so push those edits there now instead of on panel close. Autosave skips an invalid form.
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
            // Entries reference flow state paths directly; this node has no input map.
            input_map: {},
            output_variable_path: mode === 'read' ? this.form.value.output_variable_path || null : null,
            data: {
                persistence_table: this.form.value.persistence_table ?? null,
                mode,
                entries: entryValues
                    .filter((entryValue) => !isEmptyEntry(entryValue))
                    .map((entryValue) =>
                        normalizeEntry(
                            {
                                ...entryValue,
                                value: entryValue.value?.trim(),
                                default: parseDefaultValue(entryValue.default ?? ''),
                            },
                            mode
                        )
                    ),
            },
        };
    }

    protected addEntry(): void {
        this.entries.push(this.createEntryGroup({ key: '', value: WRITE_VALUE_PREFILL }, this.mode()));
    }

    protected removeEntry(index: number): void {
        this.entries.removeAt(index);
    }

    protected onKeyInput(entryIndex: number, event: Event): void {
        const input = event.target as HTMLInputElement;
        this.suggestionTarget.set({ entryIndex, input });
        this.keySearch$.next({ entryIndex, search: input.value });
    }

    protected onKeyKeydown(event: KeyboardEvent): void {
        const count = this.keySuggestions().length;
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
                this.pickKeySuggestion(this.keySuggestions()[this.activeSuggestionIndex()]);
                break;
            case 'Escape':
                // Keeps the shortcut listener from closing the whole panel.
                event.preventDefault();
                event.stopPropagation();
                this.dismissSuggestions();
                break;
        }
    }

    protected onKeyBlur(): void {
        this.dismissSuggestions();
    }

    protected isSuggestionListOpen(entryIndex: number): boolean {
        return this.suggestionTarget()?.entryIndex === entryIndex && this.keySuggestions().length > 0;
    }

    /** The untouched `variables.` prefill is not an error yet; the user is about to type the rest. */
    protected valueHintFor(index: number): string | null {
        const value = this.entries.at(index).get('value');
        if (!value?.hasError('pattern')) return null;
        if (value.value === WRITE_VALUE_PREFILL && value.pristine && value.untouched) return null;
        return writeValueHint(value.value);
    }

    protected badgeFor(index: number): ExistenceBadge {
        const key: string = this.entries.at(index).value.key ?? '';
        return existenceBadge(this.mode(), key, this.lookups()[key]);
    }

    private onModeChange(form: FormGroup, newMode: PersistenceMode): void {
        if (newMode === this.mode()) return;
        this.mode.set(newMode);

        const entriesArray = form.get('entries') as FormArray;
        const reshaped = reshapeEntriesForMode(entriesArray.getRawValue(), newMode);
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
        const key = [
            entry.key,
            unlessEmptyEntry(Validators.required, Validators.maxLength(PERSISTENCE_KEY_MAX_LENGTH)),
        ];
        if (mode === 'read') {
            const defaultValue = 'default' in entry && entry.default !== undefined ? JSON.stringify(entry.default) : '';
            return {
                alias: ['alias' in entry ? entry.alias : '', unlessEmptyEntry(Validators.required)],
                key,
                default: [defaultValue],
            };
        }
        if (mode === 'write') {
            return {
                key,
                value: ['value' in entry ? entry.value : '', unlessEmptyEntry(Validators.required, statePathValidator)],
            };
        }
        return { key };
    }

    private pickKeySuggestion(key: string): void {
        const target = this.suggestionTarget();
        if (target === null) return;
        const keyControl = this.entries.at(target.entryIndex).get('key');
        keyControl?.setValue(key);
        keyControl?.markAsDirty();
        this.dismissSuggestions();
    }

    private dismissSuggestions(): void {
        this.suggestionTarget.set(null);
        this.keySuggestions.set([]);
    }

    private showKeySuggestions(result: KeySearchResult): void {
        if (this.suggestionTarget()?.entryIndex !== result.entryIndex) return;
        this.activeSuggestionIndex.set(0);
        this.keySuggestions.set(result.keys);
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
        dropdown.itemSelected.subscribe((key) => this.pickKeySuggestion(key));
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
        // The existence badges are a hint; a failed lookup just hides them.
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
        return this.persistenceTablesApi.getEntries({ table, search, limit: KEY_SUGGESTION_LIMIT, offset: 0 }).pipe(
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

// Empty is left to Validators.required.
function statePathValidator(control: AbstractControl<string>): ValidationErrors | null {
    return !control.value || isStatePath(control.value) ? null : { pattern: true };
}

function canvasSummary(form: FormGroup): string {
    const { mode, persistence_table } = form.getRawValue();
    const entries: EntryFormValue[] = (form.get('entries') as FormArray).getRawValue();
    // Empty rows are not saved, so they don't count toward the canvas key count.
    const keyCount = entries.filter((entry) => !isEmptyEntry(entry)).length;
    return JSON.stringify([mode, persistence_table, keyCount]);
}

import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
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
    isSameLookupRequest,
    isStaticKey,
    LookupRequest,
    missingPlaceholders,
    normalizeEntry,
    parseDefaultValue,
    reshapeEntriesForMode,
} from '../../../core/helpers/persistence-node.helpers';
import { PersistenceNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { PersistenceEntry, PersistenceMode } from '../../../core/models/persistence-node.model';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import { createInputMapFromPairs, getValidInputPairs, initializeInputMap } from '../node-panel-form.utils';

// Mirrors MAX_KEY_LENGTH in tables/constants/persistence_constants.py.
const PERSISTENCE_KEY_MAX_LENGTH = 512;
const KEY_SUGGESTION_LIMIT = 20;
const CANVAS_SYNC_DEBOUNCE_MS = 300;

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
        InputMapComponent,
        ValidationErrorsComponent,
        SelectComponent,
        AppSvgIconComponent,
    ],
    templateUrl: './persistence-node-panel.component.html',
    styleUrls: ['./persistence-node-panel.component.scss'],
})
export class PersistenceNodePanelComponent extends BaseSidePanel<PersistenceNodeModel> {
    protected readonly mode = signal<PersistenceMode>('read');
    protected readonly loadingTables = signal(false);
    protected readonly lookups = signal<PersistenceEntryLookupResponse>({});
    protected readonly missingPlaceholderHints = signal<Record<number, string[]>>({});
    protected readonly keySuggestions = signal<string[]>([]);
    protected readonly canReadData = computed(() => this.permissions.can(ResourceCode.PersistentData, ActionCode.Read));
    protected readonly tableItems = computed<SelectItem<number | null>[]>(() => [
        { name: 'Select a table', value: null },
        ...this.persistenceTablesStorage.tables().map((table) => ({ name: table.name, value: table.id })),
    ]);
    protected readonly keySuggestionsListId = computed(() => `persistence-key-suggestions-${this.node().id}`);

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
    private readonly keySearch$ = new Subject<string>();

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
            .subscribe((keys) => this.keySuggestions.set(keys));
    }

    protected get entries(): FormArray {
        return this.form.get('entries') as FormArray;
    }

    protected get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
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
            input_map: this.fb.array([]),
            output_variable_path: [node.output_variable_path ?? ''],
        });

        initializeInputMap(form, node.input_map as Record<string, unknown> | null | undefined, this.fb);

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
            input_map: createInputMapFromPairs(getValidInputPairs(this.inputMapPairs)),
            output_variable_path: mode === 'delete' ? null : this.form.value.output_variable_path || null,
            data: {
                persistence_table: this.form.value.persistence_table ?? null,
                mode,
                entries: entryValues.map((entryValue) =>
                    normalizeEntry({ ...entryValue, default: parseDefaultValue(entryValue.default ?? '') }, mode)
                ),
            },
        };
    }

    protected addEntry(): void {
        this.entries.push(this.createEntryGroup({ key: '' }, this.mode()));
    }

    protected removeEntry(index: number): void {
        this.entries.removeAt(index);
    }

    protected onKeyInput(event: Event): void {
        this.keySearch$.next((event.target as HTMLInputElement).value);
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
        const key = [entry.key, [Validators.required, Validators.maxLength(PERSISTENCE_KEY_MAX_LENGTH)]];
        if (mode === 'read') {
            const defaultValue = 'default' in entry && entry.default !== undefined ? JSON.stringify(entry.default) : '';
            return this.fb.group({
                alias: ['alias' in entry ? entry.alias : '', Validators.required],
                key,
                default: [defaultValue],
            });
        }
        if (mode === 'write') {
            return this.fb.group({ key, value: ['value' in entry ? entry.value : '', Validators.required] });
        }
        return this.fb.group({ key });
    }

    private refreshPlaceholderHints(form: FormGroup): void {
        const inputMapKeys = (form.get('input_map') as FormArray).controls.map((pair) =>
            ((pair.value.key as string) ?? '').trim()
        );
        const hints: Record<number, string[]> = {};
        (form.get('entries') as FormArray).controls.forEach((entry, index) => {
            const missing = missingPlaceholders(entry.value.key ?? '', inputMapKeys);
            if (missing.length > 0) hints[index] = missing;
        });
        this.missingPlaceholderHints.set(hints);
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

    private fetchKeySuggestions(search: string): Observable<string[]> {
        const table: number | null = this.form.get('persistence_table')?.value ?? null;
        if (table === null || !this.canReadData()) {
            return of([]);
        }
        return this.persistenceTablesApi.getEntries({ table, search, limit: KEY_SUGGESTION_LIMIT, offset: 0 }).pipe(
            map((page) => page.results.map((entry) => entry.key)),
            catchError(() => of([]))
        );
    }
}

function canvasSummary(form: FormGroup): string {
    const { mode, persistence_table } = form.getRawValue();
    return JSON.stringify([mode, persistence_table, (form.get('entries') as FormArray).length]);
}

import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    Injector,
    input,
    OnInit,
    output,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    CheckboxComponent,
    ConfirmationDialogData,
    ConfirmationDialogService,
    SearchComponent,
} from '@shared/components';
import { downloadBlob, escapeHtml } from '@shared/utils';
import { catchError, EMPTY, filter, finalize, Observable, switchMap, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import {
    AuditEnumOption,
    AuditFilterMode,
    AuditFilterState,
    AuditMatchScopeState,
} from '../../models/audit-filter.models';
import { AuditPreset, AuditPresetScope } from '../../models/audit-preset.models';
import { AuditPresetsApiService } from '../../services/audit-presets-api.service';
import { AuditPresetsStorageService } from '../../services/audit-presets-storage.service';
import { buildPresetBody, restorePresetState } from '../../utils/audit-preset-body.util';
import { selectionState, toggleAll, toggleOne } from '../../utils/audit-preset-selection.util';
import {
    AuditFilterChip,
    AuditFilterVocabularies,
    clearAuditFilterField,
    describeAuditFilter,
} from '../../utils/describe-audit-filter.util';
import { AuditMatchScopeComponent } from '../audit-match-scope/audit-match-scope.component';

const MAX_CARD_CHIPS = 3;
const NAME_ERROR_PREFIX = 'name: ';
const FIELD_ERROR_SEPARATOR = '; ';
// Key of the presets block in the backend import summary.
const PRESET_IMPORT_ENTITY = 'AuditFilterPreset';
const SHARE_DIALOG_MESSAGE = 'This preset will become available to your team in Shared Presets.';
const DIALOG_CONFIG = { width: '485px', panelClass: 'audit-preset-dialog-panel' };

interface AuditPresetEditor {
    presetId: number | null;
    name: string;
    state: AuditFilterState;
    applyOnSave: boolean;
    error: string | null;
    isSaving: boolean;
}

interface AuditPresetCard {
    preset: AuditPreset;
    state: AuditFilterState | null;
    modeLabel: string;
    chips: AuditFilterChip[];
    hiddenChipCount: number;
    author: string | null;
}

function presetCount(count: number): string {
    return `${count} preset${count === 1 ? '' : 's'}`;
}

function modeLabel(state: AuditFilterState | null): string {
    if (state === null) {
        return 'API';
    }
    return state.mode === 'query' ? 'Query code' : 'Builder';
}

@Component({
    selector: 'app-audit-presets',
    imports: [
        AppSvgIconComponent,
        AuditMatchScopeComponent,
        CheckboxComponent,
        NgTemplateOutlet,
        OverlayModule,
        SearchComponent,
    ],
    templateUrl: './audit-presets.component.html',
    styleUrl: './audit-presets.component.scss',
})
export class AuditPresetsComponent implements OnInit {
    public readonly scope = input.required<AuditPresetScope>();
    public readonly currentFilter = input.required<AuditFilterState>();
    public readonly agentOptions = input<AuditEnumOption[]>([]);
    public readonly toolOptions = input<AuditEnumOption[]>([]);
    public readonly openCreateOnInit = input<boolean>(false);
    public readonly presetApplied = output<AuditFilterState>();
    public readonly queryCopied = output<string>();

    private readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');
    private readonly menuItems = viewChildren<ElementRef<HTMLButtonElement>>('menuItem');

    protected readonly searchTerm = signal('');
    protected readonly openMenuId = signal<number | null>(null);
    protected readonly editor = signal<AuditPresetEditor | null>(null);
    protected readonly isSelecting = signal(false);
    protected readonly isExporting = signal(false);
    protected readonly isImporting = signal(false);
    private readonly selectedIds = signal<ReadonlySet<number>>(new Set());

    protected readonly isLoading = computed(() => this.presetsStorage.isLoading());
    protected readonly loadError = computed(() => this.presetsStorage.loadError());

    private readonly vocabularies = computed<AuditFilterVocabularies>(() => ({
        agents: this.agentOptions(),
        tools: this.toolOptions(),
    }));

    protected readonly scopedPresets = computed(() => this.presetsStorage.presetsInScope(this.scope()));

    protected readonly cards = computed<AuditPresetCard[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        return this.scopedPresets()
            .filter((preset) => preset.name.toLowerCase().includes(term))
            .map((preset) => this.toCard(preset));
    });

    // Presets that left this tab (moved, deleted) drop out of the selection on their own.
    private readonly selectedInScope = computed(() =>
        this.scopedPresets()
            .filter((preset) => this.selectedIds().has(preset.id))
            .map((preset) => preset.id)
    );
    private readonly listedIds = computed(() => this.cards().map((card) => card.preset.id));

    protected readonly selectAll = computed(() => selectionState(this.selectedIds(), this.listedIds()));
    protected readonly selectionLabel = computed(() => {
        const count = this.selectedInScope().length;
        return count === 0 ? 'Nothing selected' : `${count} selected`;
    });
    protected readonly canExportSelected = computed(() => this.selectedInScope().length > 0 && !this.isExporting());

    protected readonly isCreating = computed(() => this.editor()?.presetId === null);
    protected readonly isSaving = computed(() => this.editor()?.isSaving === true);

    protected readonly editedPreset = computed(() => {
        const presetId = this.editor()?.presetId;
        return this.presetsStorage.presets().find((preset) => preset.id === presetId) ?? null;
    });

    protected readonly editorChips = computed<AuditFilterChip[]>(() => {
        const editor = this.editor();
        if (editor === null) {
            return [];
        }
        return describeAuditFilter({ ...editor.state, mode: 'builder' }, this.vocabularies()).filter(
            (chip) => chip.key !== 'matchScope'
        );
    });

    protected readonly canSave = computed(() => {
        const editor = this.editor();
        return editor !== null && editor.name.trim() !== '' && !editor.isSaving;
    });

    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    protected readonly unavailableHint = "Created outside the filters panel — it can't be opened here";

    private readonly presetsStorage = inject(AuditPresetsStorageService);
    private readonly presetsApi = inject(AuditPresetsApiService);
    private readonly toastService = inject(ToastService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    public ngOnInit(): void {
        if (this.openCreateOnInit()) {
            this.openCreate(true);
        }
    }

    protected openCreate(applyOnSave = false): void {
        this.openEditor({ presetId: null, name: '', state: this.currentFilter(), applyOnSave });
    }

    protected openEdit(card: AuditPresetCard): void {
        this.closeMenu(card.preset.id);
        if (card.state === null) {
            return;
        }
        this.openEditor({ presetId: card.preset.id, name: card.preset.name, state: card.state, applyOnSave: false });
    }

    protected cancelEdit(): void {
        if (!this.isSaving()) {
            this.editor.set(null);
        }
    }

    protected setEditorName(event: Event): void {
        this.updateEditor({ name: (event.target as HTMLInputElement).value, error: null });
    }

    protected setEditorMode(mode: AuditFilterMode): void {
        this.updateEditorState({ mode });
    }

    protected setEditorMatchScope(matchScope: AuditMatchScopeState): void {
        this.updateEditorState({ matchScope });
    }

    protected setEditorQuery(event: Event): void {
        this.updateEditorState({ query: (event.target as HTMLTextAreaElement).value });
    }

    // same clearing the toolbar chips use, applied to the preset being edited
    protected removeEditorFilter(key: string): void {
        this.editor.update((editor) =>
            editor === null ? null : { ...editor, state: clearAuditFilterField(editor.state, key) }
        );
    }

    protected save(): void {
        const editor = this.editor();
        if (editor === null || !this.canSave()) {
            return;
        }
        const name = editor.name.trim();
        const filterBody = buildPresetBody(editor.state);
        const request =
            editor.presetId === null
                ? this.presetsStorage.createPreset(name, filterBody, this.scope() === 'shared')
                : this.presetsStorage.updatePreset(editor.presetId, { name, filter_body: filterBody });

        this.updateEditor({ isSaving: true, error: null });
        request.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => {
                this.editor.set(null);
                if (editor.applyOnSave) {
                    this.presetApplied.emit(editor.state);
                }
            },
            error: (error: HttpErrorResponse) =>
                this.updateEditor({ isSaving: false, error: this.backendMessage(error, 'Could not save the preset.') }),
        });
    }

    protected activateCard(card: AuditPresetCard): void {
        if (this.isSelecting()) {
            this.toggleSelected(card.preset.id);
        } else if (card.state !== null) {
            this.presetApplied.emit(card.state);
        }
    }

    protected toggleMenu(presetId: number): void {
        this.openMenuId.update((current) => (current === presetId ? null : presetId));
    }

    protected closeMenu(presetId: number): void {
        this.openMenuId.update((current) => (current === presetId ? null : current));
    }

    protected focusFirstMenuItem(): void {
        this.focusAfterRender(() => this.menuItems()[0]?.nativeElement);
    }

    protected duplicate(card: AuditPresetCard): void {
        const presetId = card.preset.id;
        this.closeMenu(presetId);
        this.presetsStorage
            .duplicatePreset(presetId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                if (this.scope() === 'shared') {
                    this.toastService.success('Copied to My Presets');
                }
            });
    }

    protected overwrite(card: AuditPresetCard): void {
        this.closeMenu(card.preset.id);
        this.presetsStorage.updatePreset(card.preset.id, { filter_body: buildPresetBody(this.currentFilter()) });
    }

    protected copyQuery(card: AuditPresetCard): void {
        this.closeMenu(card.preset.id);
        if (card.state?.mode === 'query') {
            this.queryCopied.emit(card.state.query);
        }
    }

    protected confirmDelete(preset: AuditPreset): void {
        this.closeMenu(preset.id);
        this.confirmThen(
            {
                title: 'Delete preset?',
                message: `Are you sure you want to delete <strong>${escapeHtml(preset.name)}</strong> preset?`,
                caution:
                    "It will <strong>disappear</strong> from your presets list, and the filters and match scope saved in it <strong>will be lost</strong>. You'll have to set them up manually next time.",
                confirmText: 'Delete',
            },
            () => this.presetsStorage.deletePreset(preset.id)
        ).subscribe(() => {
            if (this.editor()?.presetId === preset.id) {
                this.editor.set(null);
            }
        });
    }

    protected startSelecting(): void {
        this.openMenuId.set(null);
        this.isSelecting.set(true);
    }

    protected stopSelecting(): void {
        this.isSelecting.set(false);
        this.selectedIds.set(new Set());
    }

    protected isSelected(presetId: number): boolean {
        return this.selectedIds().has(presetId);
    }

    protected toggleSelected(presetId: number): void {
        this.selectedIds.update((selected) => toggleOne(selected, presetId));
    }

    protected toggleSelectAll(): void {
        this.selectedIds.update((selected) => toggleAll(selected, this.listedIds()));
    }

    protected exportSelected(): void {
        this.isExporting.set(true);
        this.download(this.presetsApi.exportPresets(this.selectedInScope()), `audit-presets-export-${Date.now()}.json`)
            .pipe(finalize(() => this.isExporting.set(false)))
            .subscribe(() => this.stopSelecting());
    }

    protected exportPreset(preset: AuditPreset): void {
        this.closeMenu(preset.id);
        this.download(this.presetsApi.exportPreset(preset.id), `${preset.name}.json`).subscribe();
    }

    protected importFile(event: Event): void {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        input.value = '';
        if (file === undefined) {
            return;
        }
        this.isImporting.set(true);
        this.presetsStorage
            .importPresets(file)
            .pipe(
                finalize(() => this.isImporting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (summary) => {
                    const created = summary[PRESET_IMPORT_ENTITY]?.created.count ?? 0;
                    const reused = summary[PRESET_IMPORT_ENTITY]?.reused.count ?? 0;
                    this.toastService.success(
                        created === 0 && reused > 0
                            ? `No new presets — ${presetCount(reused)} already existed`
                            : `Imported ${presetCount(created)} to My Presets`
                    );
                },
                error: (error: HttpErrorResponse) => this.toastError(error, 'Could not import presets.'),
            });
    }

    protected confirmMoveToShared(preset: AuditPreset): void {
        this.closeMenu(preset.id);
        this.confirmShare(
            'Move Preset to Shared Presets?',
            "It will be visible to all users of your organization and can't be made private again. Only you can change it.",
            'Move to Shared Presets',
            () => this.presetsStorage.updatePreset(preset.id, { is_shared: true }),
            'Moved to Shared Presets'
        );
    }

    protected confirmCopyToShared(preset: AuditPreset): void {
        this.closeMenu(preset.id);
        this.confirmShare(
            'Copy Preset to Shared Presets?',
            'A copy of this preset will be visible to all users of your organization. Only you can change it.',
            'Copy to Shared Presets',
            () => this.presetsStorage.duplicatePreset(preset.id, true),
            'Copied to Shared Presets'
        );
    }

    private confirmShare(
        title: string,
        caution: string,
        confirmText: string,
        request: () => Observable<AuditPreset>,
        successMessage: string
    ): void {
        this.confirmThen({ title, message: SHARE_DIALOG_MESSAGE, caution, confirmText }, request).subscribe({
            next: () => this.toastService.success(successMessage),
            error: (error: HttpErrorResponse) => this.toastError(error, 'Could not share the preset.'),
        });
    }

    private confirmThen<T>(
        dialog: Pick<ConfirmationDialogData, 'title' | 'message' | 'caution' | 'confirmText'>,
        request: () => Observable<T>
    ): Observable<T> {
        return this.confirmationDialog
            .confirm({ ...dialog, cautionTitle: 'Attention', cancelText: 'Cancel', type: 'warning' }, DIALOG_CONFIG)
            .pipe(
                filter((result) => result === true),
                switchMap(request),
                takeUntilDestroyed(this.destroyRef)
            );
    }

    // A generic toast on export failure is deliberate: the error body arrives as a Blob, and decoding it
    // for a message is not worth it for the rare 400 (an id that is no longer visible).
    private download(request: Observable<Blob>, filename: string): Observable<Blob> {
        return request.pipe(
            tap({
                next: (blob) => downloadBlob(blob, filename),
                error: (error: HttpErrorResponse) => this.toastError(error, 'Could not export presets.'),
            }),
            catchError(() => EMPTY),
            takeUntilDestroyed(this.destroyRef)
        );
    }

    private toCard(preset: AuditPreset): AuditPresetCard {
        const state = restorePresetState(preset.filter_body);
        const chips = state === null ? [] : describeAuditFilter(state, this.vocabularies());
        return {
            preset,
            state,
            modeLabel: modeLabel(state),
            chips: chips.slice(0, MAX_CARD_CHIPS),
            hiddenChipCount: Math.max(chips.length - MAX_CARD_CHIPS, 0),
            author: this.authorLabel(preset),
        };
    }

    private authorLabel(preset: AuditPreset): string | null {
        if (this.scope() !== 'shared') {
            return null;
        }
        return preset.is_owner ? 'You' : preset.created_by_name;
    }

    private openEditor(fields: Pick<AuditPresetEditor, 'presetId' | 'name' | 'state' | 'applyOnSave'>): void {
        this.editor.set({ ...fields, error: null, isSaving: false });
        this.focusAfterRender(() => this.nameInput()?.nativeElement);
    }

    private focusAfterRender(target: () => HTMLElement | undefined): void {
        afterNextRender(() => target()?.focus(), { injector: this.injector });
    }

    private updateEditor(change: Partial<AuditPresetEditor>): void {
        this.editor.update((editor) => (editor === null ? null : { ...editor, ...change }));
    }

    private updateEditorState(change: Partial<AuditFilterState>): void {
        this.editor.update((editor) => (editor === null ? null : { ...editor, state: { ...editor.state, ...change } }));
    }

    // The forbidden interceptor already toasts a 403.
    private toastError(error: HttpErrorResponse, fallback: string): void {
        if (error.status !== 403) {
            this.toastService.error(this.backendMessage(error, fallback));
        }
    }

    // First field error of a 400, without the `name: ` label the user doesn't need to see.
    private backendMessage(error: HttpErrorResponse, fallback: string): string {
        const message: unknown = error.status === 400 ? error.error?.message : null;
        const firstError = typeof message === 'string' ? message.split(FIELD_ERROR_SEPARATOR)[0] : '';
        if (firstError === '') {
            return fallback;
        }
        return firstError.startsWith(NAME_ERROR_PREFIX) ? firstError.slice(NAME_ERROR_PREFIX.length) : firstError;
    }
}

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
import { AppSvgIconComponent, ConfirmationDialogService, SearchComponent } from '@shared/components';
import { filter, switchMap } from 'rxjs';

import {
    AuditEnumOption,
    AuditFilterMode,
    AuditFilterState,
    AuditMatchScopeState,
} from '../../models/audit-filter.models';
import { AuditPreset } from '../../models/audit-preset.models';
import { AuditPresetsApiService } from '../../services/audit-presets-api.service';
import { buildPresetBody, restorePresetState } from '../../utils/audit-preset-body.util';
import { AuditFilterChip, AuditFilterVocabularies, describeAuditFilter } from '../../utils/describe-audit-filter.util';
import { AuditMatchScopeComponent } from '../audit-match-scope/audit-match-scope.component';

const MAX_CARD_CHIPS = 3;
const NAME_ERROR_PREFIX = 'name: ';
const FIELD_ERROR_SEPARATOR = '; ';

const HTML_ESCAPES: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
};

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
}

function escapeHtml(text: string): string {
    return text.replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);
}

function modeLabel(state: AuditFilterState | null): string {
    if (state === null) {
        return 'API';
    }
    return state.mode === 'query' ? 'Query code' : 'Builder';
}

@Component({
    selector: 'app-audit-presets',
    imports: [AppSvgIconComponent, AuditMatchScopeComponent, NgTemplateOutlet, OverlayModule, SearchComponent],
    templateUrl: './audit-presets.component.html',
    styleUrl: './audit-presets.component.scss',
})
export class AuditPresetsComponent implements OnInit {
    public readonly currentFilter = input.required<AuditFilterState>();
    public readonly agentOptions = input<AuditEnumOption[]>([]);
    public readonly toolOptions = input<AuditEnumOption[]>([]);
    public readonly openCreateOnInit = input<boolean>(false);
    public readonly presetApplied = output<AuditFilterState>();
    public readonly queryCopied = output<string>();

    private readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');
    private readonly menuItems = viewChildren<ElementRef<HTMLButtonElement>>('menuItem');

    protected readonly presets = signal<AuditPreset[]>([]);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal(false);
    protected readonly searchTerm = signal('');
    protected readonly openMenuId = signal<number | null>(null);
    protected readonly editor = signal<AuditPresetEditor | null>(null);

    private readonly vocabularies = computed<AuditFilterVocabularies>(() => ({
        agents: this.agentOptions(),
        tools: this.toolOptions(),
    }));

    protected readonly cards = computed<AuditPresetCard[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        return this.presets()
            .filter((preset) => preset.name.toLowerCase().includes(term))
            .map((preset) => this.toCard(preset));
    });

    protected readonly isCreating = computed(() => this.editor()?.presetId === null);
    protected readonly isSaving = computed(() => this.editor()?.isSaving === true);

    protected readonly editedPreset = computed(() => {
        const presetId = this.editor()?.presetId;
        return this.presets().find((preset) => preset.id === presetId) ?? null;
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
    protected readonly queryOnlyHint = 'Only for presets built with Query code';

    private readonly presetsApi = inject(AuditPresetsApiService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    public ngOnInit(): void {
        this.loadPresets();
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

    protected save(): void {
        const editor = this.editor();
        if (editor === null || !this.canSave()) {
            return;
        }
        const name = editor.name.trim();
        const filterBody = buildPresetBody(editor.state);
        const request =
            editor.presetId === null
                ? this.presetsApi.createPreset(name, filterBody)
                : this.presetsApi.updatePreset(editor.presetId, { name, filter_body: filterBody });

        this.updateEditor({ isSaving: true, error: null });
        request.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (saved) => {
                if (editor.presetId === null) {
                    this.presets.update((presets) => [saved, ...presets]);
                } else {
                    this.replacePreset(saved);
                }
                this.editor.set(null);
                if (editor.applyOnSave) {
                    this.presetApplied.emit(editor.state);
                }
            },
            error: (error: HttpErrorResponse) =>
                this.updateEditor({ isSaving: false, error: this.saveErrorMessage(error) }),
        });
    }

    protected applyPreset(card: AuditPresetCard): void {
        if (card.state !== null) {
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
        this.presetsApi
            .duplicatePreset(presetId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((copy) =>
                this.presets.update((presets) => {
                    const index = presets.findIndex((preset) => preset.id === presetId);
                    return [...presets.slice(0, index + 1), copy, ...presets.slice(index + 1)];
                })
            );
    }

    protected overwrite(card: AuditPresetCard): void {
        this.closeMenu(card.preset.id);
        this.presetsApi
            .updatePreset(card.preset.id, { filter_body: buildPresetBody(this.currentFilter()) })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((saved) => this.replacePreset(saved));
    }

    protected copyQuery(card: AuditPresetCard): void {
        this.closeMenu(card.preset.id);
        if (card.state?.mode === 'query') {
            this.queryCopied.emit(card.state.query);
        }
    }

    protected confirmDelete(preset: AuditPreset): void {
        this.closeMenu(preset.id);
        this.confirmationDialog
            .confirm({
                title: 'Delete preset?',
                message: `Are you sure you want to delete <strong>${escapeHtml(preset.name)}</strong> preset?`,
                cautionTitle: 'Attention',
                caution:
                    "It will <strong>disappear</strong> from your presets list, and the filters and match scope saved in it <strong>will be lost</strong>. You'll have to set them up manually next time.",
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(
                filter((result) => result === true),
                switchMap(() => this.presetsApi.deletePreset(preset.id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => {
                this.presets.update((presets) => presets.filter((item) => item.id !== preset.id));
                if (this.editor()?.presetId === preset.id) {
                    this.editor.set(null);
                }
            });
    }

    private loadPresets(): void {
        this.isLoading.set(true);
        this.loadError.set(false);
        this.presetsApi
            .getPresets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (presets) => {
                    this.presets.set(presets);
                    this.isLoading.set(false);
                },
                error: () => {
                    this.loadError.set(true);
                    this.isLoading.set(false);
                },
            });
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
        };
    }

    private openEditor(fields: Pick<AuditPresetEditor, 'presetId' | 'name' | 'state' | 'applyOnSave'>): void {
        this.editor.set({ ...fields, error: null, isSaving: false });
        this.focusAfterRender(() => this.nameInput()?.nativeElement);
    }

    private focusAfterRender(target: () => HTMLElement | undefined): void {
        afterNextRender(() => target()?.focus(), { injector: this.injector });
    }

    private replacePreset(saved: AuditPreset): void {
        this.presets.update((presets) => presets.map((preset) => (preset.id === saved.id ? saved : preset)));
    }

    private updateEditor(change: Partial<AuditPresetEditor>): void {
        this.editor.update((editor) => (editor === null ? null : { ...editor, ...change }));
    }

    private updateEditorState(change: Partial<AuditFilterState>): void {
        this.editor.update((editor) => (editor === null ? null : { ...editor, state: { ...editor.state, ...change } }));
    }

    private saveErrorMessage(error: HttpErrorResponse): string {
        const message: unknown = error.status === 400 ? error.error?.message : null;
        const firstError = typeof message === 'string' ? message.split(FIELD_ERROR_SEPARATOR)[0] : '';
        if (firstError.startsWith(NAME_ERROR_PREFIX)) {
            return firstError.slice(NAME_ERROR_PREFIX.length);
        }
        return 'Could not save the preset.';
    }
}

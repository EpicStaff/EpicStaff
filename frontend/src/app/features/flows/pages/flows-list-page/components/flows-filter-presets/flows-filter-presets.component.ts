import {
    afterNextRender,
    ChangeDetectionStrategy,
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
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ConfirmationDialogService, SearchComponent } from '@shared/components';
import { escapeHtml } from '@shared/utils';

import { FlowFilterPreset } from '../../../../models/flow-filter-preset.model';
import { FlowFilterPresetsStorageService } from '../../../../services/flow-filter-presets-storage.service';
import { FlowsStorageService } from '../../../../services/flows-storage.service';
import { describeFlowFilter, FilterChip } from '../../../../utils/describe-flow-filter.util';
import { buildFlowPresetBody, restoreFlowPresetState } from '../../../../utils/flow-filter-preset-body.util';

const MAX_CARD_CHIPS = 3;

interface FlowPresetCard {
    preset: FlowFilterPreset;
    chips: FilterChip[];
    hiddenChipCount: number;
}

@Component({
    selector: 'app-flows-filter-presets',
    imports: [AppSvgIconComponent, SearchComponent, MatTooltip],
    templateUrl: './flows-filter-presets.component.html',
    styleUrls: ['./flows-filter-presets.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsFilterPresetsComponent implements OnInit {
    public readonly openCreateOnInit = input<boolean>(false);
    public readonly presetApplied = output<void>();

    private readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');
    private readonly renameInput = viewChild<ElementRef<HTMLInputElement>>('renameInput');
    private readonly presetButtons = viewChildren<ElementRef<HTMLButtonElement>>('presetButton');

    protected readonly presetName = signal('');
    protected readonly searchTerm = signal('');
    protected readonly editingPresetId = signal<number | null>(null);
    protected readonly editingPresetName = signal('');
    protected readonly isSaving = signal(false);
    protected readonly showCreateForm = signal(false);

    protected readonly isLoading = computed(() => this.presetsStorage.isLoading());
    protected readonly loadError = computed(() => this.presetsStorage.loadError());
    protected readonly presets = computed(() => this.presetsStorage.presets());
    protected readonly filteredPresets = computed(() => {
        const term = this.searchTerm().trim().toLowerCase();
        if (!term) return this.presets();
        return this.presets().filter((preset) => preset.name.toLowerCase().includes(term));
    });
    protected readonly filteredCards = computed<FlowPresetCard[]>(() =>
        this.filteredPresets().map((preset) => this.toCard(preset))
    );
    protected readonly canSave = computed(() => this.presetName().trim() !== '' && !this.isSaving());

    private readonly presetsStorage = inject(FlowFilterPresetsStorageService);
    private readonly flowsStorage = inject(FlowsStorageService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    public ngOnInit(): void {
        if (this.openCreateOnInit()) {
            this.showCreateForm.set(true);
            afterNextRender(() => this.nameInput()?.nativeElement.focus(), { injector: this.injector });
        }
    }

    protected applyPreset(preset: FlowFilterPreset): void {
        const restored = restoreFlowPresetState(preset.filter_body);
        this.flowsStorage.patchFilter(restored);
        this.presetApplied.emit();
    }

    protected overwritePreset(preset: FlowFilterPreset): void {
        this.presetsStorage
            .updatePreset(preset.id, { filter_body: buildFlowPresetBody(this.flowsStorage.getCurrentFilter()) })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }

    protected saveNewPreset(): void {
        const name = this.presetName().trim();
        if (!name) {
            return;
        }
        this.isSaving.set(true);
        this.presetsStorage
            .createPreset(name, buildFlowPresetBody(this.flowsStorage.getCurrentFilter()))
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.presetName.set('');
                    this.isSaving.set(false);
                    this.showCreateForm.set(false);
                },
                error: () => this.isSaving.set(false),
            });
    }

    protected startRename(preset: FlowFilterPreset): void {
        this.editingPresetId.set(preset.id);
        this.editingPresetName.set(preset.name);
        afterNextRender(() => this.renameInput()?.nativeElement.focus(), { injector: this.injector });
    }

    protected setRenameName(event: Event): void {
        this.editingPresetName.set((event.target as HTMLInputElement).value);
    }

    /** Ends the rename; `returnFocus` (Enter) puts the focus back on the preset, as the field it was in goes away. */
    protected confirmRename(presetId: number, returnFocus = false): void {
        const focusPresetId = returnFocus ? presetId : null;
        const name = this.editingPresetName().trim();
        if (!name) {
            this.cancelRename(focusPresetId);
            return;
        }
        this.presetsStorage
            .updatePreset(presetId, { name })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.cancelRename(focusPresetId));
    }

    protected cancelRename(focusPresetId: number | null = null): void {
        this.editingPresetId.set(null);
        this.editingPresetName.set('');
        if (focusPresetId !== null) {
            afterNextRender(() => this.focusPreset(focusPresetId), { injector: this.injector });
        }
    }

    protected confirmDelete(preset: FlowFilterPreset): void {
        this.confirmationDialog
            .confirm({
                title: 'Delete preset?',
                message: `Are you sure you want to delete <strong>${escapeHtml(preset.name)}</strong>?`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.presetsStorage.deletePreset(preset.id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
                }
            });
    }

    protected setNewPresetName(event: Event): void {
        this.presetName.set((event.target as HTMLInputElement).value);
    }

    private toCard(preset: FlowFilterPreset): FlowPresetCard {
        const state = restoreFlowPresetState(preset.filter_body);
        const chips = describeFlowFilter(state);
        return {
            preset,
            chips: chips.slice(0, MAX_CARD_CHIPS),
            hiddenChipCount: Math.max(chips.length - MAX_CARD_CHIPS, 0),
        };
    }

    private focusPreset(presetId: number): void {
        const presetButton = this.presetButtons().find(
            (button) => button.nativeElement.dataset['presetId'] === String(presetId)
        );
        presetButton?.nativeElement.focus();
    }
}

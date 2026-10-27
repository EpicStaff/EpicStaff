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
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ConfirmationDialogService, SearchComponent } from '@shared/components';
import { escapeHtml } from '@shared/utils';

import { ToolFilterPreset } from '../../../../models/tool-filter-preset.model';
import { ToolFilterPresetsStorageService } from '../../../../services/tool-filter-presets-storage.service';
import { ToolsViewStorageService } from '../../../../services/tools-view-storage.service';
import { describeToolFilter, FilterChip } from '../../../../utils/describe-tool-filter.util';
import { buildPresetBody, restorePresetState } from '../../../../utils/tool-filter-preset-body.util';

const MAX_CARD_CHIPS = 3;

interface ToolPresetCard {
    preset: ToolFilterPreset;
    chips: FilterChip[];
    hiddenChipCount: number;
}

@Component({
    selector: 'app-tools-filter-presets',
    imports: [AppSvgIconComponent, SearchComponent],
    templateUrl: './tools-filter-presets.component.html',
    styleUrls: ['./tools-filter-presets.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsFilterPresetsComponent implements OnInit {
    public readonly openCreateOnInit = input<boolean>(false);
    public readonly presetApplied = output<void>();

    private readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');
    private readonly renameInput = viewChild<ElementRef<HTMLInputElement>>('renameInput');

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
    protected readonly filteredCards = computed<ToolPresetCard[]>(() =>
        this.filteredPresets().map((preset) => this.toCard(preset))
    );
    protected readonly canSave = computed(() => this.presetName().trim() !== '' && !this.isSaving());

    private readonly presetsStorage = inject(ToolFilterPresetsStorageService);
    private readonly viewState = inject(ToolsViewStorageService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    public ngOnInit(): void {
        if (this.openCreateOnInit()) {
            this.showCreateForm.set(true);
            afterNextRender(() => this.nameInput()?.nativeElement.focus(), { injector: this.injector });
        }
    }

    protected applyPreset(preset: ToolFilterPreset): void {
        const restored = restorePresetState(preset.filter_body);
        this.viewState.patchFilter(restored);
        this.presetApplied.emit();
    }

    protected overwritePreset(preset: ToolFilterPreset): void {
        this.presetsStorage
            .updatePreset(preset.id, { filter_body: buildPresetBody(this.viewState.filter()) })
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
            .createPreset(name, buildPresetBody(this.viewState.filter()))
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

    protected startRename(preset: ToolFilterPreset): void {
        this.editingPresetId.set(preset.id);
        this.editingPresetName.set(preset.name);
        afterNextRender(() => this.renameInput()?.nativeElement.focus(), { injector: this.injector });
    }

    protected setRenameName(event: Event): void {
        this.editingPresetName.set((event.target as HTMLInputElement).value);
    }

    protected confirmRename(presetId: number): void {
        const name = this.editingPresetName().trim();
        if (!name) {
            this.cancelRename();
            return;
        }
        this.presetsStorage
            .updatePreset(presetId, { name })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.cancelRename());
    }

    protected cancelRename(): void {
        this.editingPresetId.set(null);
        this.editingPresetName.set('');
    }

    protected confirmDelete(preset: ToolFilterPreset): void {
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

    private toCard(preset: ToolFilterPreset): ToolPresetCard {
        const state = restorePresetState(preset.filter_body);
        const chips = describeToolFilter(state);
        return {
            preset,
            chips: chips.slice(0, MAX_CARD_CHIPS),
            hiddenChipCount: Math.max(chips.length - MAX_CARD_CHIPS, 0),
        };
    }
}

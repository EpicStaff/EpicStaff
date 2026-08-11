import { Dialog } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnInit,
    output,
    signal,
    untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ConfirmationDialogService, LlmModelSelectorComponent } from '@shared/components';
import { EnterBlurDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';

import { ToastService } from '../../../../../../services/notifications/toast.service';
import { StorageItem } from '../../../../../files/models/storage.models';
import { StorageApiService } from '../../../../../files/services/storage-api.service';
import { StorageDragService } from '../../../../../files/services/storage-drag.service';
import {
    ExtractTextFromStorageDialogComponent,
    ExtractTextFromStorageDialogResult,
} from '../../../../components/extract-text-from-storage-dialog/extract-text-from-storage-dialog.component';
import { AgentDefinition, AgentSurfacePlace } from '../../../../models/agent-definition.model';
import { RealtimeAgentDefinition } from '../../../../models/realtime-agent-definition.model';
import { CreateSurfaceRequest, PartialUpdateSurfaceRequest, Surface } from '../../../../models/surface.model';
import { SurfaceCategoryId } from '../../../../models/surface-category.model';
import { RealtimeAgentDefinitionsApiService } from '../../../../services/realtime-agent-definitions-api.service';
import { SurfaceDragService } from '../../../../services/surface-drag.service';
import { INSTRUCTIONS_ACCEPT_ATTR, readFileAsText } from '../../../../utils/instructions-file.utils';
import {
    AgentAdditionalSettingsData,
    AgentAdditionalSettingsDialogComponent,
    AgentAdditionalSettingsResult,
} from './agent-additional-settings-dialog/agent-additional-settings-dialog.component';
import { AgentSurfacesPanelComponent } from './agent-surfaces-panel/agent-surfaces-panel.component';

export interface AgentSavePayload {
    id: number | null;
    name: string;
    description: string;
    instructions: string;
    llm_config: number | null;
    fcm_llm_config: number | null;
    max_iter?: number;
    max_rpm?: number;
    max_execution_time?: number;
    cache?: boolean;
    max_retry_limit?: number;
    default_temperature?: number;
    max_tool_calls?: number | null;
    tool_timeout?: number | null;
    max_consecutive_failures?: number | null;
    schema_max_retries?: number | null;
}

export type AgentSectionId = 'basics' | 'surfaces';

interface AgentFormValue {
    name: string;
    description: string;
    instructions: string;
    llm_config: number | null;
}

@Component({
    selector: 'app-agent-detail',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        AppSvgIconComponent,
        LlmModelSelectorComponent,
        HideInlineSubtitleOnOverflowDirective,
        EnterBlurDirective,
        AgentSurfacesPanelComponent,
        MatTooltipModule,
    ],
    templateUrl: './agent-detail.component.html',
    styleUrls: ['./agent-detail.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentDetailComponent implements OnInit {
    private readonly fb: FormBuilder = inject(FormBuilder);
    private readonly destroyRef: DestroyRef = inject(DestroyRef);
    private readonly dialog: Dialog = inject(Dialog);
    private readonly confirm: ConfirmationDialogService = inject(ConfirmationDialogService);
    private readonly storageApiService: StorageApiService = inject(StorageApiService);
    private readonly storageDrag = inject(StorageDragService);
    private readonly surfaceDrag = inject(SurfaceDragService);
    private readonly toast: ToastService = inject(ToastService);
    private readonly realtimeApi = inject(RealtimeAgentDefinitionsApiService);

    readonly acceptAttr = INSTRUCTIONS_ACCEPT_ATTR;

    agent = input<AgentDefinition | null>(null);
    isCreating = input<boolean>(false);
    saving = input<boolean>(false);
    surfaces = input<Surface[]>([]);
    saveErrorTick = input<number>(0);
    bootIsDoc = input<boolean>(false);
    surfacesOnly = input<boolean>(false);
    sharedSurfaceIds = input<ReadonlySet<number>>(new Set<number>());

    readonly save = output<AgentSavePayload>();
    readonly delete = output<AgentDefinition>();
    readonly duplicate = output<AgentDefinition>();
    readonly dirtyChange = output<boolean>();
    readonly bootDocChange = output<boolean>();
    readonly openBootDoc = output<void>();
    readonly extractText = output<string>();
    readonly createSurface = output<{ body: CreateSurfaceRequest; place: SurfaceCategoryId }>();
    readonly addFromShared = output<{ surfaceId: number; category: SurfaceCategoryId }>();
    readonly dropSharedSurface = output<{ surfaceId: number; category: SurfaceCategoryId }>();
    readonly setSurfacePlaces = output<{ surfaceId: number; places: AgentSurfacePlace[] }>();
    readonly makeSharedSurface = output<number>();
    readonly detachSurface = output<number>();
    readonly deleteSurfaceFromPanel = output<number>();
    readonly duplicateSurface = output<number>();
    readonly makeAgentSpecificCopy = output<number>();
    readonly openSurfaceSource = output<number>();
    readonly renameSurface = output<{ id: number; name: string }>();
    readonly surfaceChange = output<{ id: number; patch: PartialUpdateSurfaceRequest }>();
    readonly viewSummary = output<{ place: SurfaceCategoryId; surfaceIds: number[] }>();

    readonly form = this.fb.nonNullable.group({
        name: ['', [Validators.required, Validators.maxLength(255)]],
        description: [''],
        instructions: [''],
        llm_config: [null as number | null],
    });

    // RealtimeAgentDefinition row for the current agent, loaded lazily when Additional
    // Settings opens (null = no realtime row / voice off). Seeds the dialog and decides
    // create-vs-patch when saving realtime_config.
    private realtimeDef: RealtimeAgentDefinition | null = null;

    readonly bootAsDoc = signal<boolean>(false);
    readonly bootDocName = 'Boot_Instructions.md';

    private static readonly BOOT_SUGGEST_AT = 100;
    private static readonly BOOT_URGE_AT = 250;
    readonly bootLength = signal<number>(0);
    readonly bootHintLevel = computed<'none' | 'suggest' | 'urge'>(() => {
        const n = this.bootLength();
        if (n > AgentDetailComponent.BOOT_URGE_AT) return 'urge';
        if (n > AgentDetailComponent.BOOT_SUGGEST_AT) return 'suggest';
        return 'none';
    });

    readonly sections = signal<Record<AgentSectionId, boolean>>({
        basics: true,
        surfaces: false,
    });

    private savedSnapshot = this.emptyValue();

    private seededKey: string | null = null;

    constructor() {
        effect(() => {
            const a = this.agent();
            const creating = this.isCreating();
            this.bootAsDoc.set(!creating && this.bootIsDoc());

            const key = creating ? 'creating' : a ? `agent:${a.id}` : null;
            if (key === this.seededKey) return;
            this.seededKey = key;

            if (creating) {
                this.form.reset(this.emptyValue());
                this.sections.set({ basics: true, surfaces: false });
            } else if (a) {
                this.form.reset(this.valueFromAgent(a));
                this.form.markAsPristine();
            }
            this.savedSnapshot = this.form.getRawValue();
            this.bootLength.set((this.form.controls.instructions.value ?? '').length);
            this.dirtyChange.emit(this.form.dirty);
        });

        effect(() => {
            this.saveErrorTick();
            untracked(() => this.revertToSnapshot());
        });

        // While a storage item or shared surface is being dragged, an agent shown in the
        // preview opens straight on its Surfaces section (Basics collapsed) — it's the drop area.
        effect(() => {
            if (!this.storageDrag.isDragging() && !this.surfaceDrag.isDragging()) return;
            if (!this.agent()) return;
            untracked(() => this.sections.set({ basics: false, surfaces: true }));
        });
    }

    ngOnInit(): void {
        // The LLM data (configs/models/providers) is loaded by the embedded
        // app-llm-model-selector itself, which also shows its own loading spinner — so no
        // redundant load here.
        this.form.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.dirtyChange.emit(this.form.dirty));
    }

    isOpen(id: AgentSectionId): boolean {
        return this.sections()[id];
    }

    toggleSection(id: AgentSectionId): void {
        this.sections.update((s) => ({ ...s, [id]: !s[id] }));
    }

    autosaveName(): void {
        this.persist(true);
    }

    autosave(): void {
        this.persist(false);
    }

    private persist(fromNameBlur: boolean): void {
        if (this.saving() || this.form.invalid) return;
        const v = this.form.getRawValue();
        if (!v.name.trim()) return;

        const a = this.agent();
        const creating = a?.id == null;
        if (creating && !fromNameBlur) return;
        if (this.sameAsSnapshot(v)) return;

        this.savedSnapshot = v;
        this.save.emit({
            id: a?.id ?? null,
            name: v.name.trim(),
            description: v.description ?? '',
            instructions: v.instructions ?? '',
            llm_config: v.llm_config,
            fcm_llm_config: a?.fcm_llm_config ?? null,
            max_iter: a?.max_iter,
            max_rpm: a?.max_rpm,
            max_execution_time: a?.max_execution_time,
            cache: a?.cache,
            max_retry_limit: a?.max_retry_limit,
            default_temperature: a?.default_temperature,
            max_tool_calls: a?.max_tool_calls,
            tool_timeout: a?.tool_timeout,
            max_consecutive_failures: a?.max_consecutive_failures,
            schema_max_retries: a?.schema_max_retries,
        });
    }

    private emptyValue(): AgentFormValue {
        return { name: '', description: '', instructions: '', llm_config: null };
    }

    private valueFromAgent(a: AgentDefinition): AgentFormValue {
        return {
            name: a.name,
            description: a.description ?? '',
            instructions: a.instructions ?? '',
            llm_config: a.llm_config,
        };
    }

    private sameAsSnapshot(v: AgentFormValue): boolean {
        const s = this.savedSnapshot;
        return (
            v.name === s.name &&
            v.description === s.description &&
            v.instructions === s.instructions &&
            v.llm_config === s.llm_config
        );
    }

    private revertToSnapshot(): void {
        this.form.reset(this.savedSnapshot);
        this.bootLength.set((this.savedSnapshot.instructions ?? '').length);
    }

    openAdditionalSettings(): void {
        const a = this.agent();
        if (!a || this.saving()) return;
        // Realtime lives on a separate RealtimeAgentDefinition resource, so fetch it lazily
        // here (only when the gear is actually opened) rather than probing on every agent
        // selection. 404 = no realtime row yet → null (getByAgentId maps it).
        this.realtimeApi
            .getByAgentId(a.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (rt) => this.openSettingsDialog(a, rt),
                error: () => this.openSettingsDialog(a, null),
            });
    }

    private openSettingsDialog(a: AgentDefinition, realtimeDef: RealtimeAgentDefinition | null): void {
        this.realtimeDef = realtimeDef;
        const data: AgentAdditionalSettingsData = {
            fcm_llm_config: a.fcm_llm_config,
            realtime_config: realtimeDef?.realtime_config ?? null,
            max_iter: a.max_iter,
            max_rpm: a.max_rpm,
            max_execution_time: a.max_execution_time,
            max_retry_limit: a.max_retry_limit,
            cache: a.cache,
            max_tool_calls: a.max_tool_calls,
            tool_timeout: a.tool_timeout,
            max_consecutive_failures: a.max_consecutive_failures,
            schema_max_retries: a.schema_max_retries,
        };
        this.dialog
            .open<AgentAdditionalSettingsResult | undefined>(AgentAdditionalSettingsDialogComponent, { data })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (!result) return;
                this.persistRealtimeConfig(a.id, result.realtime_config);
                const v = this.form.getRawValue();
                this.savedSnapshot = { ...v, name: v.name.trim() || a.name };
                this.save.emit({
                    id: a.id,
                    name: v.name.trim() || a.name,
                    description: v.description ?? '',
                    instructions: v.instructions ?? '',
                    llm_config: v.llm_config,
                    fcm_llm_config: result.fcm_llm_config,
                    max_iter: result.max_iter,
                    max_rpm: result.max_rpm,
                    max_execution_time: result.max_execution_time,
                    cache: result.cache,
                    max_retry_limit: result.max_retry_limit,
                    default_temperature: a.default_temperature,
                    max_tool_calls: result.max_tool_calls,
                    tool_timeout: result.tool_timeout,
                    max_consecutive_failures: result.max_consecutive_failures,
                    schema_max_retries: result.schema_max_retries,
                });
            });
    }

    // realtime_config lives on RealtimeAgentDefinition, not AgentDefinition.
    // Patch existing row, or create one when the agent first gets a realtime model
    // (that is what makes the agent appear on Chats → Agents).
    private persistRealtimeConfig(agentId: number, realtimeConfig: number | null): void {
        const current = this.realtimeDef?.realtime_config ?? null;
        if (realtimeConfig === current) return;

        if (this.realtimeDef) {
            this.realtimeApi
                .partialUpdate(agentId, { realtime_config: realtimeConfig })
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (rt) => (this.realtimeDef = rt),
                    error: () => this.toast.error('Failed to save realtime config'),
                });
            return;
        }

        if (realtimeConfig == null) return;

        this.realtimeApi
            .create({ agent_definition: agentId, realtime_config: realtimeConfig })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (rt) => (this.realtimeDef = rt),
                error: () => this.toast.error('Failed to save realtime config'),
            });
    }

    createBootDoc(): void {
        this.bootAsDoc.set(true);
        this.bootDocChange.emit(true);
    }

    removeBootDoc(): void {
        this.bootAsDoc.set(false);
        this.bootDocChange.emit(false);
    }

    onOpenBootDoc(): void {
        this.openBootDoc.emit();
    }

    /** "Extract Text from PC": open the native file picker (no upload). */
    onExtractFromPc(input: HTMLInputElement): void {
        input.click();
    }

    onPcFileSelected(event: Event): void {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        input.value = ''; // allow re-picking the same file
        if (!file) return;
        readFileAsText(file)
            .then((text) => this.applyExtractedText(text))
            .catch(() => this.toast.error(`Failed to read "${file.name}"`));
    }

    /** "Extract Text from Storage": pick a text file from storage and read it. */
    onExtractFromStorage(): void {
        const ref = this.dialog.open<ExtractTextFromStorageDialogResult | undefined>(
            ExtractTextFromStorageDialogComponent
        );
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (!result) return;
            this.readStorageFile(result.item);
        });
    }

    private readStorageFile(item: StorageItem): void {
        this.storageApiService
            .downloadBlob(item.path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) =>
                    readFileAsText(blob)
                        .then((text) => this.applyExtractedText(text))
                        .catch(() => this.toast.error(`Failed to read "${item.name}"`)),
                error: () => this.toast.error(`Failed to load "${item.name}" from storage`),
            });
    }

    /** Emit the extracted text, warning first if instructions already exist. */
    private applyExtractedText(text: string): void {
        if (this.agent()?.id == null) {
            this.toast.info('Save the agent before importing instructions');
            return;
        }
        const hasExisting = (this.form.controls.instructions.value ?? '').trim().length > 0;
        if (!hasExisting) {
            this.extractText.emit(text);
            return;
        }
        this.confirm
            .confirm({
                title: 'Replace boot instructions?',
                message: 'This will overwrite the current boot instructions with the file contents.',
                confirmText: 'Replace',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) this.extractText.emit(text);
            });
    }

    adjustTextareaHeight(textarea: HTMLTextAreaElement, maxPx: number): void {
        textarea.style.height = 'auto';
        const full = textarea.scrollHeight;
        textarea.style.height = `${Math.min(full, maxPx)}px`;
        textarea.style.overflowY = full > maxPx ? 'auto' : 'hidden';
    }

    onDelete(): void {
        const a = this.agent();
        if (a) this.delete.emit(a);
    }

    onDuplicate(): void {
        const a = this.agent();
        if (a) this.duplicate.emit(a);
    }
}

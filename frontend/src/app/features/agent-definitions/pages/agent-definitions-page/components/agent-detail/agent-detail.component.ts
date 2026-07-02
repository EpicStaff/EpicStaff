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
import { AppSvgIconComponent, LlmModelSelectorComponent } from '@shared/components';
import { EnterBlurDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { FullLLMConfig, FullLLMConfigService } from '@shared/services';

import { AgentDefinition } from '../../../../models/agent-definition.model';
import { CreateSurfaceRequest, PartialUpdateSurfaceRequest, Surface } from '../../../../models/surface.model';
import { SurfaceCategoryId } from '../../../../models/surface-category.model';
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
    private readonly fullLlmConfigService: FullLLMConfigService = inject(FullLLMConfigService);
    private readonly destroyRef: DestroyRef = inject(DestroyRef);

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
    readonly createSurface = output<{ body: CreateSurfaceRequest; place: SurfaceCategoryId }>();
    readonly addFromShared = output<number>();
    readonly moveSurfacePlace = output<{ id: number; place: SurfaceCategoryId }>();
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

    readonly llmConfigs = signal<FullLLMConfig[]>([]);
    readonly llmLoading = signal<boolean>(true);

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
    }

    ngOnInit(): void {
        this.fullLlmConfigService
            .getFullLLMConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (configs) => {
                    this.llmConfigs.set(configs);
                    this.llmLoading.set(false);
                },
                error: () => this.llmLoading.set(false),
            });

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

    createBootDoc(): void {
        this.bootAsDoc.set(true);
        this.bootDocChange.emit(true);
    }

    removeBootDoc(): void {
        this.bootAsDoc.set(false);
        this.bootDocChange.emit(false);
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

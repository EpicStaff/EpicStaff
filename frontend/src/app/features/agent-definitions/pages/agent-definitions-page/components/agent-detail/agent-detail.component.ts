import { Dialog } from '@angular/cdk/dialog';
import {
    afterRenderEffect,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    OnInit,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, HelpTooltipComponent, LlmModelSelectorComponent } from '@shared/components';
import { EnterBlurDirective, HasPermissionDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode, GetLlmConfigRequest, LabelDto, ResourceCode } from '@shared/models';
import { FullLLMConfigService } from '@shared/services';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../services/notifications';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../../../create-agent-tour/create-agent-tour-anchors';
import { StorageDragService } from '../../../../../files/services/storage-drag.service';
import { AgentDefinition, AgentInstruction, AgentSurfacePlace } from '../../../../models/agent-definition.model';
import { AgentFocus, AgentSelection } from '../../../../models/explorer.model';
import { RealtimeAgentDefinition } from '../../../../models/realtime-agent-definition.model';
import {
    CreateSurfaceRequest,
    PartialUpdateSurfaceRequest,
    Surface,
    SurfaceSaveError,
} from '../../../../models/surface.model';
import { SurfaceCategoryId } from '../../../../models/surface-category.model';
import { RealtimeAgentDefinitionsApiService } from '../../../../services/realtime-agent-definitions-api.service';
import { SurfaceDragService } from '../../../../services/surface-drag.service';
import {
    AgentAdditionalSettingsData,
    AgentAdditionalSettingsDialogComponent,
    AgentAdditionalSettingsResult,
} from './agent-additional-settings-dialog/agent-additional-settings-dialog.component';
import { AgentInstructionsListComponent } from './agent-instructions-list/agent-instructions-list.component';
import { AgentSurfacesPanelComponent } from './agent-surfaces-panel/agent-surfaces-panel.component';

export interface AgentSavePayload {
    id: number | null;
    name: string;
    description: string;
    /** Only sent when creating; existing agents save their list via `instructionListChange`. */
    instruction_list?: AgentInstruction[];
    openFirstInstructionInEdit?: boolean;
    llm_config: number | null;
    fallback_llm_config: number | null;
    fcm_llm_config: number | null;
    max_iter?: number;
    max_rpm?: number;
    max_execution_time?: number;
    prompt_caching_enabled?: boolean;
    max_retry_limit?: number;
    default_temperature?: number | null;
    max_tool_calls?: number;
    tool_timeout?: number;
    max_consecutive_failures?: number;
    schema_max_retries?: number;
}

export type AgentSectionId = 'basics' | 'surfaces';

/** Seeding key of a draft; the draft id follows it. */
const DRAFT_KEY_PREFIX = 'draft:';

const SECTIONS_BY_FOCUS: Record<AgentFocus, Record<AgentSectionId, boolean>> = {
    all: { basics: true, surfaces: true },
    instructions: { basics: true, surfaces: false },
    surfaces: { basics: false, surfaces: true },
};

interface RealtimeProviderConfig {
    openai_config: number | null;
    elevenlabs_config: number | null;
    gemini_config: number | null;
    voice: string;
}

interface AgentFormValue {
    name: string;
    description: string;
    llm_config: number | null;
    fallback_llm_config: number | null;
}

@Component({
    selector: 'app-agent-detail',
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        LlmModelSelectorComponent,
        HelpTooltipComponent,
        HideInlineSubtitleOnOverflowDirective,
        EnterBlurDirective,
        AgentSurfacesPanelComponent,
        AgentInstructionsListComponent,
        MatTooltipModule,
        HasPermissionDirective,
    ],
    templateUrl: './agent-detail.component.html',
    styleUrls: ['./agent-detail.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentDetailComponent implements OnInit {
    private readonly fb: FormBuilder = inject(FormBuilder);
    private readonly destroyRef: DestroyRef = inject(DestroyRef);
    private readonly dialog: Dialog = inject(Dialog);
    private readonly storageDrag = inject(StorageDragService);
    private readonly surfaceDrag = inject(SurfaceDragService);
    private readonly toast: ToastService = inject(ToastService);
    private readonly host: ElementRef<HTMLElement> = inject(ElementRef);
    private readonly permissionService = inject(PermissionsService);
    private readonly realtimeApi = inject(RealtimeAgentDefinitionsApiService);
    private readonly llmConfigService = inject(FullLLMConfigService);

    agent = input<AgentDefinition | null>(null);
    isCreating = input<boolean>(false);
    /** Which draft `isCreating` shows: a new value starts a new, empty one. */
    draftId = input<number>(0);
    /** Whether `agent` is the one the latest draft was saved as; only then are the draft's edits carried over. */
    createdFromDraft = input<boolean>(false);
    saving = input<boolean>(false);
    surfaces = input<Surface[]>([]);
    saveErrorTick = input<number>(0);
    surfaceSaveError = input<SurfaceSaveError | null>(null);
    surfaceCreateErrorTick = input<number>(0);
    instructionListError = input<string | null>(null);
    /** Applied on every new reference, so re-selecting the same agent re-opens and scrolls up. */
    focusRequest = input<AgentSelection | null>(null);
    sharedSurfaceIds = input<ReadonlySet<number>>(new Set<number>());
    /** The groups in explorer order, for grouping the shared surfaces offered to attach. */
    groups = input<LabelDto[]>([]);
    /** When true, disables the reactive form and blocks save/delete/duplicate emissions. */
    readOnly = input<boolean>(false);

    readonly save = output<AgentSavePayload>();
    readonly delete = output<AgentDefinition>();
    readonly duplicate = output<AgentDefinition>();
    readonly dirtyChange = output<boolean>();
    readonly instructionListChange = output<AgentInstruction[]>();
    readonly openInstruction = output<{ index: number; edit: boolean }>();
    readonly createSurface = output<{ body: CreateSurfaceRequest; place: SurfaceCategoryId }>();
    readonly setSharedInCategory = output<{ surfaceIds: number[]; category: SurfaceCategoryId }>();
    readonly dropSharedSurface = output<{ surfaceId: number; category: SurfaceCategoryId }>();
    readonly setSurfacePlaces = output<{ surfaceId: number; places: AgentSurfacePlace[] }>();
    readonly makeSharedSurface = output<number>();
    readonly detachSurface = output<number>();
    readonly deleteSurfaceFromPanel = output<number>();
    readonly duplicateSurface = output<number>();
    readonly makeAgentSpecificCopy = output<number>();
    readonly openSurfaceSource = output<number>();
    readonly openSurfaceUsage = output<number>();
    readonly renameSurface = output<{ id: number; name: string }>();
    readonly surfaceChange = output<{ id: number; patch: PartialUpdateSurfaceRequest }>();
    readonly viewSummary = output<{ place: SurfaceCategoryId; surfaceIds: number[] }>();

    readonly canOpenSettings = computed<boolean>(() => {
        return (
            this.permissionService.can(ResourceCode.LlmConfigs, ActionCode.Read) &&
            this.permissionService.can(ResourceCode.Voice, ActionCode.Read) &&
            this.permissionService.can(ResourceCode.Agents, ActionCode.Update)
        );
    });

    readonly form = this.fb.nonNullable.group({
        name: ['', [Validators.required, Validators.maxLength(255)]],
        description: [''],
        llm_config: [null as number | null],
        fallback_llm_config: [null as number | null],
    });

    // Live (unsaved) LLM selection — the Surfaces panel's RAG config needs this
    // immediately when creating/editing an agent, not just after autosave round-trips.
    readonly liveLlmConfigId = toSignal(this.form.controls.llm_config.valueChanges, {
        initialValue: this.form.controls.llm_config.value,
    });

    readonly instructionList = computed<AgentInstruction[]>(() => this.agent()?.instruction_list ?? []);

    readonly sections = signal<Record<AgentSectionId, boolean>>({
        basics: true,
        surfaces: false,
    });

    private savedSnapshot = this.emptyValue();

    private autosaveHeld = false;

    private seededKey: string | null = null;

    private readonly agentNameInput = viewChild<ElementRef<HTMLInputElement>>('agentNameInput');

    /** Set by `requireName()`; the error shows while the name is still empty. */
    private readonly nameRequested = signal<boolean>(false);
    private readonly nameValue = toSignal(this.form.controls.name.valueChanges, {
        initialValue: this.form.controls.name.value,
    });
    protected readonly showNameRequired = computed<boolean>(() => this.nameRequested() && !this.nameValue().trim());

    /** Bumped by `requireName()` to focus the name again; each new draft focuses it once on its own. */
    private readonly nameFocusRequest = signal<number>(0);
    private focusedNameRequest: string | null = null;

    private readonly focusAgentNameOnCreate = afterRenderEffect(() => {
        const creating = this.isCreating();
        const request = `${this.draftId()}:${this.nameFocusRequest()}`;
        const input = this.agentNameInput()?.nativeElement;
        if (!creating || !input) {
            if (!creating) this.focusedNameRequest = null;
            return;
        }
        if (this.focusedNameRequest === request) return;
        this.focusedNameRequest = request;
        input.focus();
    });

    constructor() {
        effect(() => {
            const a = this.agent();
            const creating = this.isCreating();

            const key = creating ? `${DRAFT_KEY_PREFIX}${this.draftId()}` : a ? `agent:${a.id}` : null;
            if (key === this.seededKey) return;
            // Leaving a draft for any other agent (after Discard & Leave) must not carry the draft's edits to it.
            const wasCreating = (this.seededKey?.startsWith(DRAFT_KEY_PREFIX) ?? false) && this.createdFromDraft();
            this.seededKey = key;
            this.nameRequested.set(false);

            if (creating) {
                this.form.reset(this.emptyValue());
                this.sections.set({ basics: true, surfaces: false });
                this.savedSnapshot = this.form.getRawValue();
            } else if (a) {
                const serverValue = this.valueFromAgent(a);
                // The create request already left. Edits made while it was in flight are only in
                // the form — keep them and save them once this agent exists.
                const next = wasCreating ? this.withEditsMadeWhileCreating(serverValue) : serverValue;
                this.form.reset(next);
                this.form.markAsPristine();
                this.savedSnapshot = wasCreating ? serverValue : next;
            }
            this.dirtyChange.emit(this.hasUnsavedEdits());
            if (wasCreating && a) {
                untracked(() => this.persist(false));
            }
        });

        effect(() => {
            this.saveErrorTick();
            untracked(() => this.keepFailedEdits());
        });

        // While a storage item or shared surface is being dragged, an agent shown in the
        // preview opens straight on its Surfaces section (Basics collapsed) — it's the drop area.
        effect(() => {
            if (!this.isDragging()) return;
            if (!this.agent()) return;
            untracked(() => this.sections.set({ basics: false, surfaces: true }));
        });

        effect(() => {
            const request = this.focusRequest();
            if (!request) return;
            untracked(() => {
                this.sections.set(this.isDragging() ? SECTIONS_BY_FOCUS.surfaces : SECTIONS_BY_FOCUS[request.focus]);
                this.host.nativeElement.scrollTo({ top: 0 });
            });
        });

        // Reflect readOnly on the reactive form so text fields render disabled.
        effect(() => {
            if (this.readOnly()) {
                this.form.disable({ emitEvent: false });
            } else {
                this.form.enable({ emitEvent: false });
            }
        });
    }

    ngOnInit(): void {
        // The LLM data (configs/models/providers) is loaded by the embedded
        // app-llm-model-selector itself, which also shows its own loading spinner — so no
        // redundant load here.
        this.form.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.dirtyChange.emit(this.hasUnsavedEdits()));
    }

    private isDragging(): boolean {
        return this.storageDrag.isDragging() || this.surfaceDrag.isDragging();
    }

    isOpen(id: AgentSectionId): boolean {
        return this.sections()[id];
    }

    toggleSection(id: AgentSectionId): void {
        this.sections.update((s) => ({ ...s, [id]: !s[id] }));
    }

    /** A draft can't be created without a name: opens Basics, focuses the name and shows that it is required. */
    requireName(): void {
        if (!this.isCreating()) return;
        this.sections.update((sections) => ({ ...sections, basics: true }));
        this.nameRequested.set(true);
        this.nameFocusRequest.update((request) => request + 1);
    }

    autosaveName(): void {
        this.keepSavedNameIfEmptied();
        this.persist(true);
    }

    autosave(): void {
        this.persist(false);
    }

    /** Whether the form can be saved as it is: editable, and named (or keeping the saved name) within the limit. */
    canSave(): boolean {
        const name = this.form.controls.name;
        return !this.readOnly() && !name.hasError('maxlength') && !!(name.value.trim() || this.savedSnapshot.name);
    }

    /**
     * Sends the pending edits as leaving the name field would. Unlike a blur it doesn't hold back while the page is
     * busy: the page calls it once no agent save is under way, and the other saves don't touch these fields.
     */
    savePendingEdits(): void {
        this.keepSavedNameIfEmptied();
        this.sendSave(true);
    }

    /** Drops the edits: the form goes back to what the server holds. */
    discardEdits(): void {
        this.savedSnapshot = this.serverValue();
        this.form.reset(this.savedSnapshot);
    }

    /** Held while a leave dialog is open: it takes the focus, and that blur must not save behind it. */
    holdAutosave(held: boolean): void {
        this.autosaveHeld = held;
    }

    /** The backend rejects a fallback with no primary or equal to it, so drop it in the same save. */
    onPrimaryLlmSelected(): void {
        const { llm_config, fallback_llm_config } = this.form.getRawValue();
        if (fallback_llm_config != null && (llm_config == null || llm_config === fallback_llm_config)) {
            this.form.controls.fallback_llm_config.setValue(null);
        }
        this.persist(false);
    }

    private keepSavedNameIfEmptied(): void {
        if (!this.form.controls.name.value.trim() && this.agent()?.id != null) {
            this.form.controls.name.setValue(this.savedSnapshot.name);
            this.toast.info("Agent name can't be empty — kept the previous name");
        }
    }

    private persist(fromNameBlur: boolean): void {
        if (!this.saving() && !this.autosaveHeld) this.sendSave(fromNameBlur);
    }

    private sendSave(fromNameBlur: boolean): void {
        if (!this.canSave()) return;

        const v = this.form.getRawValue();
        const effectiveName = v.name.trim() || this.savedSnapshot.name;

        const a = this.agent();
        const creating = a?.id == null;
        if (creating && !fromNameBlur) return;

        const candidate: AgentFormValue = { ...v, name: effectiveName };
        if (this.sameAsSnapshot(candidate)) return;

        this.savedSnapshot = candidate;
        this.save.emit({
            id: a?.id ?? null,
            name: effectiveName,
            description: v.description ?? '',
            llm_config: v.llm_config,
            fallback_llm_config: v.fallback_llm_config,
            fcm_llm_config: a?.fcm_llm_config ?? null,
            max_iter: a?.max_iter,
            max_rpm: a?.max_rpm,
            max_execution_time: a?.max_execution_time,
            prompt_caching_enabled: a?.prompt_caching_enabled,
            max_retry_limit: a?.max_retry_limit,
            default_temperature: a?.default_temperature,
            max_tool_calls: a?.max_tool_calls,
            tool_timeout: a?.tool_timeout,
            max_consecutive_failures: a?.max_consecutive_failures,
            schema_max_retries: a?.schema_max_retries,
        });
    }

    private emptyValue(): AgentFormValue {
        return { name: '', description: '', llm_config: null, fallback_llm_config: null };
    }

    /**
     * The created agent with the fields edited after the create request was sent: those the form holds otherwise than
     * the request (`savedSnapshot`) did. A name differing only in surrounding spaces was not edited, as a save trims it.
     */
    private withEditsMadeWhileCreating(serverValue: AgentFormValue): AgentFormValue {
        const local = this.form.getRawValue();
        const sent = this.savedSnapshot;
        return {
            name: local.name.trim() === sent.name ? serverValue.name : local.name,
            description: local.description === sent.description ? serverValue.description : local.description,
            llm_config: local.llm_config === sent.llm_config ? serverValue.llm_config : local.llm_config,
            fallback_llm_config:
                local.fallback_llm_config === sent.fallback_llm_config
                    ? serverValue.fallback_llm_config
                    : local.fallback_llm_config,
        };
    }

    private valueFromAgent(a: AgentDefinition): AgentFormValue {
        return {
            name: a.name,
            description: a.description ?? '',
            llm_config: a.llm_config,
            fallback_llm_config: a.fallback_llm_config,
        };
    }

    /**
     * Whether the form holds something the last save doesn't, compared the way `persist()` compares it: an
     * emptied name counts as the saved one. Angular's `dirty` stays set after an edit is undone or a name is
     * restored, so it can't tell.
     */
    private hasUnsavedEdits(): boolean {
        const value = this.form.getRawValue();
        return !this.sameAsSnapshot({ ...value, name: value.name.trim() || this.savedSnapshot.name });
    }

    private sameAsSnapshot(v: AgentFormValue): boolean {
        const s = this.savedSnapshot;
        return (
            v.name === s.name &&
            v.description === s.description &&
            v.llm_config === s.llm_config &&
            v.fallback_llm_config === s.fallback_llm_config
        );
    }

    /**
     * A failed save keeps the edits in the form: measured against what the server holds again, they count as unsaved,
     * and the next blur or leave retries them. A failed create keeps the draft the same way.
     */
    private keepFailedEdits(): void {
        this.savedSnapshot = this.serverValue();
        this.dirtyChange.emit(this.hasUnsavedEdits());
    }

    /** What the server holds for the agent shown; empty for a draft. */
    private serverValue(): AgentFormValue {
        const a = this.agent();
        return a ? this.valueFromAgent(a) : this.emptyValue();
    }

    openAdditionalSettings(): void {
        const a = this.agent();
        if (!a || this.saving()) return;

        this.realtimeApi
            .getByAgentId(a.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (realtime) => this.openSettingsDialog(a, realtime),
                error: () => this.openSettingsDialog(a, null),
            });
    }

    private openSettingsDialog(a: AgentDefinition, realtime: RealtimeAgentDefinition | null): void {
        // The model selectors load the configs only while Basics is open, so they may not be loaded yet.
        this.llmConfigService
            .getFullLLMConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (configs) => this.showSettingsDialog(a, realtime, this.isPromptCachingAvailable(configs)),
                error: () => this.showSettingsDialog(a, realtime, false),
            });
    }

    /** Whether the primary or fallback config picked in the form takes prompt-cache markers. */
    private isPromptCachingAvailable(configs: GetLlmConfigRequest[]): boolean {
        const { llm_config, fallback_llm_config } = this.form.getRawValue();
        return configs.some(
            (config) =>
                (config.id === llm_config || config.id === fallback_llm_config) && config.needs_prompt_cache_markers
        );
    }

    private showSettingsDialog(
        a: AgentDefinition,
        realtime: RealtimeAgentDefinition | null,
        promptCachingAvailable: boolean
    ): void {
        const data: AgentAdditionalSettingsData = {
            fcm_llm_config: a.fcm_llm_config,
            openai_config: realtime?.openai_config ?? null,
            elevenlabs_config: realtime?.elevenlabs_config ?? null,
            gemini_config: realtime?.gemini_config ?? null,
            voice: realtime?.voice ?? null,
            max_iter: a.max_iter,
            max_rpm: a.max_rpm,
            max_execution_time: a.max_execution_time,
            max_retry_limit: a.max_retry_limit,
            prompt_caching_enabled: a.prompt_caching_enabled,
            promptCachingAvailable,
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
                this.persistRealtimeConfig(
                    a,
                    realtime,
                    {
                        openai_config: result.openai_config,
                        elevenlabs_config: result.elevenlabs_config,
                        gemini_config: result.gemini_config,
                        voice: result.voice,
                    },
                    () => this.emitAgentSave(a, result)
                );
            });
    }

    private emitAgentSave(a: AgentDefinition, result: AgentAdditionalSettingsResult): void {
        const v = this.form.getRawValue();
        this.savedSnapshot = { ...v, name: v.name.trim() || a.name };
        this.save.emit({
            id: a.id,
            name: v.name.trim() || a.name,
            description: v.description ?? '',
            llm_config: v.llm_config,
            fallback_llm_config: v.fallback_llm_config,
            fcm_llm_config: result.fcm_llm_config,
            max_iter: result.max_iter,
            max_rpm: result.max_rpm,
            max_execution_time: result.max_execution_time,
            prompt_caching_enabled: result.prompt_caching_enabled,
            max_retry_limit: result.max_retry_limit,
            default_temperature: a.default_temperature,
            max_tool_calls: result.max_tool_calls,
            tool_timeout: result.tool_timeout,
            max_consecutive_failures: result.max_consecutive_failures,
            schema_max_retries: result.schema_max_retries,
        });
    }

    private persistRealtimeConfig(
        a: AgentDefinition,
        existing: RealtimeAgentDefinition | null,
        next: RealtimeProviderConfig,
        onDone: () => void
    ): void {
        const unchanged =
            existing != null &&
            (existing.openai_config ?? null) === next.openai_config &&
            (existing.elevenlabs_config ?? null) === next.elevenlabs_config &&
            (existing.gemini_config ?? null) === next.gemini_config &&
            (existing.voice ?? '') === next.voice;
        if (unchanged) {
            onDone();
            return;
        }

        const noneSelected = next.openai_config == null && next.elevenlabs_config == null && next.gemini_config == null;
        if (existing != null) {
            this.patchRealtimeConfig(a.id, next, onDone);
        } else if (noneSelected) {
            // No voice row and no provider picked: there is nothing to save, and no row to update.
            onDone();
        } else {
            this.createRealtimeConfig(a.id, next, onDone);
        }
    }

    private createRealtimeConfig(agentId: number, next: RealtimeProviderConfig, onDone: () => void): void {
        this.realtimeApi
            .create({ agent_definition: agentId, ...next })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => onDone(),
                error: () => {
                    this.toast.error('Failed to save realtime config');
                    onDone();
                },
            });
    }

    private patchRealtimeConfig(agentId: number, next: RealtimeProviderConfig, onDone: () => void): void {
        this.realtimeApi
            .partialUpdate(agentId, next)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => onDone(),
                error: () => {
                    this.toast.error('Failed to save realtime config');
                    onDone();
                },
            });
    }

    /** Existing agents emit the list for saving; a draft is created first, with the list as its instructions. */
    onInstructionListChange(instructionList: AgentInstruction[]): void {
        if (this.readOnly()) return;
        if (this.isCreating()) {
            this.createDraftAgentWithInstructions(instructionList);
            return;
        }
        this.instructionListChange.emit(instructionList);
    }

    private createDraftAgentWithInstructions(instructionList: AgentInstruction[]): void {
        if (this.saving()) return;
        const v = this.form.getRawValue();
        const name = v.name.trim();
        this.savedSnapshot = { ...v, name };
        this.save.emit({
            id: null,
            name,
            description: v.description ?? '',
            instruction_list: instructionList,
            openFirstInstructionInEdit: true,
            llm_config: v.llm_config,
            fallback_llm_config: v.fallback_llm_config,
            fcm_llm_config: null,
        });
    }

    adjustTextareaHeight(textarea: HTMLTextAreaElement, maxPx: number): void {
        textarea.style.height = 'auto';
        const full = textarea.scrollHeight;
        textarea.style.height = `${Math.min(full, maxPx)}px`;
        textarea.style.overflowY = full > maxPx ? 'auto' : 'hidden';
    }

    onDelete(): void {
        if (this.readOnly()) return;
        const a = this.agent();
        if (a) this.delete.emit(a);
    }

    onDuplicate(): void {
        if (this.readOnly()) return;
        const a = this.agent();
        if (a) this.duplicate.emit(a);
    }

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
    protected readonly tourAnchors = CREATE_AGENT_TOUR_ANCHORS;
}

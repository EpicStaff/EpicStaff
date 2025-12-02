import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    OnDestroy,
    OnInit,
    signal,
} from '@angular/core';
import { Dialog, DialogRef } from '@angular/cdk/dialog';
import {
    FormBuilder,
    FormGroup,
    FormControl,
    Validators,
    FormsModule,
    ReactiveFormsModule,
} from '@angular/forms';
import { CommonModule } from '@angular/common';
import { map, Subscription, switchMap, takeUntil, forkJoin } from 'rxjs';
import { Subject } from 'rxjs';
import { MATERIAL_FORMS } from '../../material-forms';

import { RealtimeAgentService } from '../../../services/realtime-agent.service';
import { AgentsService } from '../../../services/staff.service';
import { ToastService } from '../../../services/notifications/toast.service';
import { CollectionsService } from '../../../pages/knowledge-sources/services/source-collections.service';
import { GetSourceCollectionRequest } from '../../../pages/knowledge-sources/models/source-collection.model';
import { ToolsSelectorComponent } from '../../components/tools-selector/tools-selector.component';
import {
    FullLLMConfigService,
    FullLLMConfig,
} from '../../../features/settings-dialog/services/llms/full-llm-config.service';
import {
    CreateAgentRequest,
    GetAgentRequest,
    ToolUniqueName,
} from '../../models/agent.model';
import { buildToolIdsArray } from '../../utils/tool-ids-builder.util';
import { CustomErrorStateMatcher } from '../../error-state-matcher/custom-error-state-matcher';
import { ErrorStateMatcher } from '@angular/material/core';
import { getProviderIconPath } from '../../../features/settings-dialog/utils/get-provider-icon';
import { AppIconComponent } from '../app-icon/app-icon.component';

interface AgentFormData {
    role: string;
    goal: string;
    backstory: string;
    allow_delegation: boolean;
    memory: boolean;
    max_iter: number;
    max_rpm: number;
    max_execution_time: number;
    max_retry_limit: number;
    default_temperature: number | null;
    llm_config: number | null;
    fcm_llm_config: number | null;
    knowledge_collection: number | null;
    configured_tools: number[];
    python_code_tools: number[];
    mcp_tools: number[];
    search_limit: number;
    similarity_threshold: number;
    cache: boolean;
    respect_context_window: boolean;
}

@Component({
    selector: 'app-create-agent-form',
    templateUrl: './create-agent-form-dialog.component.html',
    styleUrls: ['./create-agent-form-dialog.component.scss'],
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        ReactiveFormsModule,
        ...MATERIAL_FORMS,
        ToolsSelectorComponent,
        AppIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: ErrorStateMatcher,
            useClass: CustomErrorStateMatcher,
        },
    ],
})
export class CreateAgentFormComponent implements OnInit, OnDestroy {
    public agentForm!: FormGroup<{
        role: FormControl<string>;
        goal: FormControl<string>;
        backstory: FormControl<string>;
        allow_delegation: FormControl<boolean>;
        memory: FormControl<boolean>;
        max_iter: FormControl<number>;
        max_rpm: FormControl<number>;
        max_execution_time: FormControl<number>;
        max_retry_limit: FormControl<number>;
        default_temperature: FormControl<number | null>;
        llm_config: FormControl<number | null>;
        fcm_llm_config: FormControl<number | null>;
        knowledge_collection: FormControl<number | null>;
        configured_tools: FormControl<number[]>;
        python_code_tools: FormControl<number[]>;
        mcp_tools: FormControl<number[]>;
        search_limit: FormControl<number>;
        similarity_threshold: FormControl<number>;
        cache: FormControl<boolean>;
        respect_context_window: FormControl<boolean>;
    }>;

    public isSubmitting = signal(false);

    // Edit mode properties
    public isEditMode: boolean = false;
    public agentToEdit?: GetAgentRequest;

    private subscriptions: Subscription = new Subscription();
    private destroy$ = new Subject<void>();

    // Icon Picker property
    public selectedIcon: string | null = null;

    // LLM configurations
    public availableLLMConfigs: FullLLMConfig[] = [];
    public llmConfigs: FullLLMConfig[] = [];

    // Knowledge sources
    public allKnowledgeSources: GetSourceCollectionRequest[] = [];
    public isLoadingKnowledgeSources = false;
    public selectedKnowledgeSourceId: number | null = null;

    // Active color for consistency with python-node design
    public get activeColor(): string {
        return '#685fff'; // Default accent color
    }

    constructor(
        private fb: FormBuilder,
        private cdr: ChangeDetectorRef,
        private agentService: AgentsService,
        private realtimeAgentService: RealtimeAgentService,
        private toastService: ToastService,
        private fullLLMConfigService: FullLLMConfigService,
        private collectionsService: CollectionsService,
        public dialogRef: DialogRef<GetAgentRequest | undefined>
    ) {
        // Check edit mode
        const data = this.dialogRef.config?.data as
            | { agent: GetAgentRequest; isEditMode: boolean }
            | undefined;
        if (data?.isEditMode && data?.agent) {
            this.isEditMode = true;
            this.agentToEdit = data.agent;
            this.selectedKnowledgeSourceId = data.agent.knowledge_collection;
        }
    }

    public ngOnInit(): void {
        this.initializeForm();
        this.loadLLMConfigs();
        this.loadKnowledgeSources();
    }

    private initializeForm(): void {
        if (this.isEditMode && this.agentToEdit) {
            const agent = this.agentToEdit;

            this.agentForm = new FormGroup({
                role: new FormControl<string>(agent.role, Validators.required),
                goal: new FormControl<string>(agent.goal, Validators.required),
                backstory: new FormControl<string>(
                    agent.backstory,
                    Validators.required
                ),
                allow_delegation: new FormControl<boolean>(
                    agent.allow_delegation
                ),
                memory: new FormControl<boolean>(agent.memory ?? false),
                max_iter: new FormControl<number>(agent.max_iter, [
                    Validators.min(1),
                    Validators.max(30),
                ]),
                max_rpm: new FormControl<number>(agent.max_rpm || 10, [
                    Validators.min(1),
                    Validators.max(30),
                ]),
                max_execution_time: new FormControl<number>(
                    agent.max_execution_time || 60,
                    [Validators.min(1), Validators.max(300)]
                ),
                max_retry_limit: new FormControl<number>(
                    agent.max_retry_limit ?? 3,
                    [Validators.min(0), Validators.max(10)]
                ),
                default_temperature: new FormControl<number | null>(null), // Set to null as requested
                llm_config: new FormControl<number | null>(agent.llm_config),
                fcm_llm_config: new FormControl<number | null>(
                    agent.fcm_llm_config
                ),
                knowledge_collection: new FormControl<number | null>(
                    agent.knowledge_collection
                ),
                configured_tools: new FormControl<number[]>(
                    agent.configured_tools || []
                ),
                python_code_tools: new FormControl<number[]>(
                    agent.python_code_tools || []
                ),
                mcp_tools: new FormControl<number[]>(
                    agent.mcp_tools || []
                ),
                search_limit: new FormControl<number>(
                    agent.search_limit || 10,
                    [Validators.min(1), Validators.max(1000)]
                ),
                similarity_threshold: new FormControl<number>(
                    Number(agent.similarity_threshold ?? 0.7),
                    [Validators.min(0), Validators.max(1.0)]
                ),
                cache: new FormControl<boolean>(agent.cache ?? true),
                respect_context_window: new FormControl<boolean>(
                    agent.respect_context_window ?? true
                ),
            }) as FormGroup<{
                role: FormControl<string>;
                goal: FormControl<string>;
                backstory: FormControl<string>;
                allow_delegation: FormControl<boolean>;
                memory: FormControl<boolean>;
                max_iter: FormControl<number>;
                max_rpm: FormControl<number>;
                max_execution_time: FormControl<number>;
                max_retry_limit: FormControl<number>;
                default_temperature: FormControl<number | null>;
                llm_config: FormControl<number | null>;
                fcm_llm_config: FormControl<number | null>;
                knowledge_collection: FormControl<number | null>;
                configured_tools: FormControl<number[]>;
                python_code_tools: FormControl<number[]>;
                mcp_tools: FormControl<number[]>;
                search_limit: FormControl<number>;
                similarity_threshold: FormControl<number>;
                cache: FormControl<boolean>;
                respect_context_window: FormControl<boolean>;
            }>;

            this.selectedKnowledgeSourceId = agent.knowledge_collection;
        } else {
            // Create new form with defaults
            this.agentForm = new FormGroup({
                role: new FormControl<string>('', Validators.required),
                goal: new FormControl<string>('', Validators.required),
                backstory: new FormControl<string>('', Validators.required),
                allow_delegation: new FormControl<boolean>(true),
                memory: new FormControl<boolean>(false),
                max_iter: new FormControl<number>(10, [
                    Validators.min(1),
                    Validators.max(30),
                ]),
                max_rpm: new FormControl<number>(10, [
                    Validators.min(1),
                    Validators.max(30),
                ]),
                max_execution_time: new FormControl<number>(60, [
                    Validators.min(1),
                    Validators.max(300),
                ]),
                max_retry_limit: new FormControl<number>(3, [
                    Validators.min(0),
                    Validators.max(10),
                ]),
                default_temperature: new FormControl<number | null>(null),
                llm_config: new FormControl<number | null>(null),
                fcm_llm_config: new FormControl<number | null>(null),
                knowledge_collection: new FormControl<number | null>(null),
                configured_tools: new FormControl<number[]>([]),
                python_code_tools: new FormControl<number[]>([]),
                mcp_tools: new FormControl<number[]>([]),
                search_limit: new FormControl<number>(10, [
                    Validators.min(1),
                    Validators.max(1000),
                ]),
                similarity_threshold: new FormControl<number>(0.7, [
                    Validators.min(0),
                    Validators.max(1.0),
                ]),
                cache: new FormControl<boolean>(true),
                respect_context_window: new FormControl<boolean>(true),
            }) as FormGroup<{
                role: FormControl<string>;
                goal: FormControl<string>;
                backstory: FormControl<string>;
                allow_delegation: FormControl<boolean>;
                memory: FormControl<boolean>;
                max_iter: FormControl<number>;
                max_rpm: FormControl<number>;
                max_execution_time: FormControl<number>;
                max_retry_limit: FormControl<number>;
                default_temperature: FormControl<number | null>;
                llm_config: FormControl<number | null>;
                fcm_llm_config: FormControl<number | null>;
                knowledge_collection: FormControl<number | null>;
                configured_tools: FormControl<number[]>;
                python_code_tools: FormControl<number[]>;
                mcp_tools: FormControl<number[]>;
                search_limit: FormControl<number>;
                similarity_threshold: FormControl<number>;
                cache: FormControl<boolean>;
                respect_context_window: FormControl<boolean>;
            }>;
        }
    }

    private loadLLMConfigs(): void {
        this.fullLLMConfigService
            .getFullLLMConfigs()
            .subscribe((configs: FullLLMConfig[]) => {
                this.availableLLMConfigs = configs;
                this.llmConfigs = configs;
                this.cdr.markForCheck();
            });
    }

    private loadKnowledgeSources(): void {
        this.isLoadingKnowledgeSources = true;
        this.collectionsService.getGetSourceCollectionRequests().subscribe({
            next: (collections) => {
                this.allKnowledgeSources = collections;
                this.isLoadingKnowledgeSources = false;
                this.cdr.markForCheck();
            },
            error: (error) => {
                console.error('Error loading knowledge sources:', error);
                this.isLoadingKnowledgeSources = false;
                this.cdr.markForCheck();
            },
        });
    }

    public onIconSelected(icon: string | null): void {
        this.selectedIcon = icon;
    }

    public onKnowledgeSourceChange(collectionId: number | null): void {
        this.selectedKnowledgeSourceId = collectionId;
        this.agentForm.patchValue({ knowledge_collection: collectionId });
    }

    // Tool selection handlers
    public onConfiguredToolsChange(toolConfigIds: number[]): void {
        this.agentForm.patchValue({ configured_tools: toolConfigIds });
        this.cdr.markForCheck();
    }

    public onPythonToolsChange(pythonToolIds: number[]): void {
        this.agentForm.patchValue({ python_code_tools: pythonToolIds });
        this.cdr.markForCheck();
    }

    public onMcpToolsChange(mcpToolIds: number[]): void {
        this.agentForm.patchValue({ mcp_tools: mcpToolIds });
        this.cdr.markForCheck();
    }

    // Helper methods for slider labels
    formatIterationLabel(value: number): string {
        return `${value}`;
    }

    formatExecutionTimeLabel(value: number): string {
        return `${value}s`;
    }

    formatRetryLimitLabel(value: number): string {
        return `${value}`;
    }

    formatRpmLabel(value: number): string {
        return `${value}`;
    }

    formatSearchLimitLabel(value: number): string {
        return `${value}`;
    }

    formatThresholdLabel(value: number): string {
        return `${value}`;
    }

    // Helper method to get provider icon
    getProviderIcon(config: FullLLMConfig): string {
        if (!config || !config.providerDetails?.name) {
            return 'llm-providers-logos/default';
        }
        return getProviderIconPath(config.providerDetails.name);
    }

    // Helper method to get LLM tooltip text
    getLLMTooltipText(config: FullLLMConfig): string {
        if (!config) {
            return 'Unknown Model';
        }

        const modelName = config.modelDetails?.name || 'Unknown Model';
        const customName = config.custom_name;
        const providerName = config.providerDetails?.name;

        let tooltip = modelName;

        if (customName) {
            tooltip += ` (${customName})`;
        }

        if (providerName) {
            tooltip += ` - ${providerName}`;
        }

        return tooltip;
    }

    // Helper method to format temperature for display
    getFormattedTemperature(config: FullLLMConfig): string {
        if (config && typeof config.temperature === 'number') {
            // Convert 0-1 to 1-100, ensuring it's at least 1 if original is 0
            const temp = Math.max(1, Math.round(config.temperature * 100));
            return `${temp}°`;
        }
        return 'N/A';
    }

    public onSubmitForm(): void {
        if (this.agentForm.invalid) {
            this.markFormGroupTouched(this.agentForm);
            return;
        }

        this.isSubmitting.set(true);

        const formData = this.agentForm.value as AgentFormData;

        // Build tool_ids array
        const configuredToolIds = formData.configured_tools || [];
        const pythonToolIds = formData.python_code_tools || [];
        const mcpToolIds = formData.mcp_tools || [];
        const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds, mcpToolIds);

        console.log('=== Agent Form Submission ===');
        console.log('Form data:', formData);
        console.log('Built tool_ids array:', toolIds);
        console.log('=== End Agent Form Data ===');

        if (this.isEditMode && this.agentToEdit) {
            // Edit mode - update existing agent
            const updateRequest = {
                ...this.agentToEdit,
                role: formData.role,
                goal: formData.goal,
                backstory: formData.backstory,
                allow_delegation: formData.allow_delegation,
                memory: formData.memory,
                max_iter: formData.max_iter,
                max_rpm: formData.max_rpm,
                max_execution_time: formData.max_execution_time,
                max_retry_limit: formData.max_retry_limit,
                default_temperature: formData.default_temperature,
                llm_config: formData.llm_config,
                fcm_llm_config: formData.fcm_llm_config,
                knowledge_collection: formData.knowledge_collection,
                configured_tools: configuredToolIds,
                python_code_tools: pythonToolIds,
                mcp_tools: mcpToolIds,
                tool_ids: toolIds as ToolUniqueName[],
                search_limit: formData.search_limit,
                similarity_threshold: formData.similarity_threshold.toString(),
                cache: formData.cache,
                respect_context_window: formData.respect_context_window,
            };

            console.log('Update request:', updateRequest);

            this.agentService.updateAgent(updateRequest).subscribe({
                next: (updatedAgent) => {
                    this.isSubmitting.set(false);

                    const completeAgent: GetAgentRequest = {
                        ...this.agentToEdit!,
                        ...updatedAgent,
                        tools: this.agentToEdit!.tools,
                    };
                    this.dialogRef.close(completeAgent);
                },
                error: (error) => {
                    this.isSubmitting.set(false);
                    console.error('Error updating agent:', error);
                    this.toastService.error('Failed to update agent');
                },
            });
        } else {
            // Create mode - add new agent
            const agentRequest: CreateAgentRequest = {
                role: formData.role,
                goal: formData.goal,
                backstory: formData.backstory,
                allow_delegation: formData.allow_delegation,
                memory: formData.memory,
                max_iter: formData.max_iter,
                max_rpm: formData.max_rpm,
                max_execution_time: formData.max_execution_time,
                max_retry_limit: formData.max_retry_limit,
                default_temperature: formData.default_temperature,
                llm_config: formData.llm_config,
                fcm_llm_config: formData.fcm_llm_config,
                knowledge_collection: formData.knowledge_collection,
                configured_tools: configuredToolIds,
                python_code_tools: pythonToolIds,
                mcp_tools: mcpToolIds,
                tool_ids: toolIds as ToolUniqueName[],
                search_limit: formData.search_limit,
                similarity_threshold: formData.similarity_threshold.toString(),
                cache: formData.cache,
                respect_context_window: formData.respect_context_window,
            };

            console.log('Create request:', agentRequest);

            this.agentService.createAgent(agentRequest).subscribe({
                next: (createdAgent: GetAgentRequest) => {
                    this.toastService.success(
                        `Agent ${createdAgent.role} created`
                    );
                    this.isSubmitting.set(false);
                    this.dialogRef.close(createdAgent);
                },
                error: (error) => {
                    this.isSubmitting.set(false);
                    console.error('Error creating agent:', error);
                    this.toastService.error('Failed to create agent');
                },
            });
        }
    }

    public onCancelForm(): void {
        this.dialogRef.close();
    }

    private markFormGroupTouched(formGroup: FormGroup): void {
        Object.values(formGroup.controls).forEach((control) => {
            control.markAsTouched();
            if (control instanceof FormGroup) {
                this.markFormGroupTouched(control);
            }
        });
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
        this.subscriptions.unsubscribe();
    }
}

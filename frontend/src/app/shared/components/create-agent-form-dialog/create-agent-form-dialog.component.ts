import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit,
} from '@angular/core';
import { Dialog, DialogRef } from '@angular/cdk/dialog';
import {
  FormBuilder,
  FormGroup,
  Validators,
  FormsModule,
  ReactiveFormsModule,
} from '@angular/forms';
import { CommonModule } from '@angular/common';
import { map, Subscription, switchMap, takeUntil, forkJoin } from 'rxjs';
import { Subject } from 'rxjs';

import { RealtimeAgentService } from '../../../services/realtime-agent.service';

import { AgentsService } from '../../../services/staff.service';
import { ToastService } from '../../../services/notifications/toast.service';
import { ShortcutListenerDirective } from '../../../visual-programming/core/directives/shortcut-listener.directive';
import { HelpTooltipComponent } from '../help-tooltip/help-tooltip.component';
import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';
import { AppIconComponent } from '../app-icon/app-icon.component';
import { FormSliderComponent } from '../form-controls/slider/form-slider.component';
import { KnowledgeSelectorComponent } from '../knowledge-selector/knowledge-selector.component';
import { CollectionsService } from '../../../pages/knowledge-sources/services/source-collections.service';
import { GetSourceCollectionRequest } from '../../../pages/knowledge-sources/models/source-collection.model';
import { ToolsSelectorComponent } from '../../components/tools-selector/tools-selector.component';
import { LlmModelSelectorComponent } from '../llm-model-selector/llm-model-selector.component';
import {
  FullLLMConfigService,
  FullLLMConfig,
} from '../../../features/settings-dialog/services/llms/full-llm-config.service';
import {
  CreateAgentRequest,
  GetAgentRequest,
  ToolUniqueName,
} from '../../models/agent.model';
import { ToggleSwitchComponent } from '../form-controls/toggle-switch/toggle-switch.component';
import { buildToolIdsArray } from '../../utils/tool-ids-builder.util';

@Component({
  selector: 'app-create-agent-form',
  templateUrl: './create-agent-form-dialog.component.html',
  styleUrls: ['./create-agent-form-dialog.component.scss'],
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    FormSliderComponent,
    ToggleSwitchComponent,
    ShortcutListenerDirective,
    HelpTooltipComponent,
    IconButtonComponent,
    AppIconComponent,
    KnowledgeSelectorComponent,
    ToolsSelectorComponent,
    LlmModelSelectorComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateAgentFormComponent implements OnInit, OnDestroy {
  public agentForm!: FormGroup;

  public temperatureValue: number = 0;
  public isSubmitting: boolean = false;
  public activeTab: 'overview' | 'configurations' = 'overview';

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
    // Check if we're in edit mode
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
    // Default values
    const defaultValues = {
      // Basic Fields
      role: '',
      goal: '',
      backstory: '',
      // Basic Advanced Fields
      allow_delegation: true,
      memory: true,
      max_iter: 10,
      // Advanced Settings
      max_rpm: 10,
      max_execution_time: 60,
      cache: true,
      allow_code_execution: true,
      max_retry_limit: 3,
      respect_context_window: true,
      default_temperature: 0,
      // LLM Configurations
      llm_config: null,
      fcm_llm_config: null,
      // Knowledge Source
      knowledge_collection: null,
      // Tools
      configured_tools: [],
      python_code_tools: [],
    };

    // If in edit mode, use agent data for initial values
    if (this.isEditMode && this.agentToEdit) {
      const agent = this.agentToEdit;

      this.agentForm = this.fb.group({
        // Basic Fields
        role: [agent.role, Validators.required],
        goal: [agent.goal, Validators.required],
        backstory: [agent.backstory, Validators.required],
        // Basic Advanced Fields
        allow_delegation: [agent.allow_delegation],
        memory: [agent.memory ?? true],
        max_iter: [agent.max_iter, [Validators.min(1)]],
        // Advanced Settings
        max_rpm: [agent.max_rpm || 10],
        max_execution_time: [agent.max_execution_time || 60],
        cache: [agent.cache ?? true],
        allow_code_execution: [agent.allow_code_execution ?? true],
        max_retry_limit: [agent.max_retry_limit || 3],
        respect_context_window: [agent.respect_context_window || true],
        default_temperature: [
          agent.default_temperature ? agent.default_temperature * 100 : 0,
        ],
        // LLM Configurations
        llm_config: [agent.llm_config],
        fcm_llm_config: [agent.fcm_llm_config],
        llmId: [agent.llm_config ? agent.llm_config : null],
        functionLlmId: [agent.fcm_llm_config ? agent.fcm_llm_config : null],
        // Knowledge Source
        knowledge_collection: [agent.knowledge_collection],
        // Tools
        configured_tools: [agent.configured_tools || []],
        python_code_tools: [agent.python_code_tools || []],
      });

      // Update UI values
      if (agent.default_temperature !== null) {
        this.temperatureValue = agent.default_temperature * 100;
      }
      this.selectedKnowledgeSourceId = agent.knowledge_collection;
    } else {
      // Create new form with defaults
      this.agentForm = this.fb.group({
        // Basic Fields
        role: ['', Validators.required],
        goal: ['', Validators.required],
        backstory: ['', Validators.required],
        // Basic Advanced Fields
        allow_delegation: [defaultValues.allow_delegation],
        memory: [defaultValues.memory], // This field is hidden in the UI but kept in the form for backend compatibility
        max_iter: [defaultValues.max_iter, [Validators.min(1)]],
        // Advanced Settings
        max_rpm: [defaultValues.max_rpm],
        max_execution_time: [defaultValues.max_execution_time],
        cache: [defaultValues.cache],
        allow_code_execution: [defaultValues.allow_code_execution],
        max_retry_limit: [defaultValues.max_retry_limit],
        respect_context_window: [defaultValues.respect_context_window],
        default_temperature: [defaultValues.default_temperature],
        // LLM Configurations
        llm_config: [defaultValues.llm_config],
        fcm_llm_config: [defaultValues.fcm_llm_config],
        llmId: [null],
        functionLlmId: [null],
        // Knowledge Source
        knowledge_collection: [defaultValues.knowledge_collection],
        // Tools
        configured_tools: [defaultValues.configured_tools],
        python_code_tools: [defaultValues.python_code_tools],
      });
    }
  }

  private loadLLMConfigs(): void {
    this.fullLLMConfigService
      .getFullLLMConfigs()
      .subscribe((configs: FullLLMConfig[]) => {
        this.availableLLMConfigs = configs;
        this.llmConfigs = configs;

        // In edit mode, update the form with the selected LLM IDs
        if (this.isEditMode && this.agentToEdit) {
          console.log('Edit mode - Setting LLM IDs from agent data');
          console.log('Agent LLM ID:', this.agentToEdit.llm_config);
          console.log('Function LLM ID:', this.agentToEdit.fcm_llm_config);

          // Force the form to update with the correct LLM IDs
          setTimeout(() => {
            this.agentForm.patchValue({
              llmId: this.agentToEdit?.llm_config,
              functionLlmId: this.agentToEdit?.fcm_llm_config,
            });
            this.cdr.markForCheck();
          });
        }

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

  public switchTab(tab: 'overview' | 'configurations'): void {
    this.activeTab = tab;
    this.cdr.markForCheck();
  }

  public onSliderInput(newValue: number): void {
    this.temperatureValue = newValue;
    // Convert 0-100 to 0-1 for temperature
    const temperature = newValue / 100;
    this.agentForm.patchValue({ default_temperature: temperature });
    this.cdr.markForCheck();
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

  public onSubmitForm(): void {
    if (this.agentForm.invalid) {
      this.markFormGroupTouched(this.agentForm);
      return;
    }

    this.isSubmitting = true;
    this.cdr.markForCheck();

    const formValues = this.agentForm.value;

    // Get the LLM IDs from the form
    const llmId = formValues.llmId;
    const functionLlmId = formValues.functionLlmId;

    // Build tool_ids array
    const configuredToolIds = formValues.configured_tools || [];
    const pythonToolIds = formValues.python_code_tools || [];
    const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds);

    console.log('=== Agent Form Submission ===');
    console.log('Form values:', formValues);
    console.log('Selected LLM ID:', llmId);
    console.log('Selected Function LLM ID:', functionLlmId);
    console.log('Configured Tool IDs:', configuredToolIds);
    console.log('Python Tool IDs:', pythonToolIds);
    console.log('Built tool_ids array:', toolIds);
    console.log('=== End Agent Form Data ===');

    if (this.isEditMode && this.agentToEdit) {
      // Edit mode - update existing agent
      const updateRequest = {
        ...this.agentToEdit,
        role: formValues.role,
        goal: formValues.goal,
        backstory: formValues.backstory,
        allow_delegation: formValues.allow_delegation,
        memory: formValues.memory,
        cache: formValues.cache,
        max_iter: formValues.max_iter,
        max_rpm: formValues.max_rpm,
        max_execution_time: formValues.max_execution_time,
        allow_code_execution: formValues.allow_code_execution,
        max_retry_limit: formValues.max_retry_limit,
        respect_context_window: formValues.respect_context_window,
        default_temperature: formValues.default_temperature / 100,
        llm_config: llmId,
        fcm_llm_config: functionLlmId,
        knowledge_collection: formValues.knowledge_collection,
        configured_tools: configuredToolIds,
        python_code_tools: pythonToolIds,
        tool_ids: toolIds as ToolUniqueName[],
      };

      console.log('Update request:', updateRequest);

      this.agentService.updateAgent(updateRequest).subscribe({
        next: (updatedAgent) => {
          this.isSubmitting = false;

          const completeAgent: GetAgentRequest = {
            ...this.agentToEdit!,
            ...updatedAgent,
            tools: this.agentToEdit!.tools,
          };
          this.dialogRef.close(completeAgent);
          this.cdr.markForCheck();
        },
        error: (error) => {
          this.isSubmitting = false;
          console.error('Error updating agent:', error);
          this.toastService.error('Failed to update agent');
          this.cdr.markForCheck();
        },
      });
    } else {
      // Create mode - add new agent
      const agentRequest: CreateAgentRequest = {
        role: formValues.role,
        goal: formValues.goal,
        backstory: formValues.backstory,
        allow_delegation: formValues.allow_delegation,
        memory: formValues.memory,
        cache: formValues.cache,
        max_iter: formValues.max_iter,
        max_rpm: formValues.max_rpm,
        max_execution_time: formValues.max_execution_time,
        allow_code_execution: formValues.allow_code_execution,
        max_retry_limit: formValues.max_retry_limit,
        respect_context_window: formValues.respect_context_window,
        default_temperature: formValues.default_temperature / 100,
        llm_config: llmId,
        fcm_llm_config: functionLlmId,
        knowledge_collection: formValues.knowledge_collection,
        configured_tools: configuredToolIds,
        python_code_tools: pythonToolIds,
        tool_ids: toolIds as ToolUniqueName[],
      };

      console.log('Create request:', agentRequest);

      this.agentService.createAgent(agentRequest).subscribe({
        next: (createdAgent: GetAgentRequest) => {
          this.toastService.success(`Agent ${createdAgent.role} created`);
          this.isSubmitting = false;
          this.dialogRef.close(createdAgent);
          this.cdr.markForCheck();
        },
        error: (error) => {
          this.isSubmitting = false;
          console.error('Error creating agent:', error);
          this.toastService.error('Failed to create agent');
          this.cdr.markForCheck();
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

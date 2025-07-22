import { Component, OnInit, OnDestroy } from '@angular/core';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { DialogModule, DialogRef } from '@angular/cdk/dialog';
import { Subject, takeUntil } from 'rxjs';
import { ToastService } from '../../../../services/notifications/toast.service';

import { IconButtonComponent } from '../../../../shared/components/buttons/icon-button/icon-button.component';
import {
  FullEmbeddingConfig,
  FullEmbeddingConfigService,
} from '../../../settings-dialog/services/embeddings/full-embedding.service';
import {
  FullLLMConfig,
  FullLLMConfigService,
} from '../../../settings-dialog/services/llms/full-llm-config.service';
import {
  GetProjectRequest,
  CreateProjectRequest,
} from '../../models/project.model';
import { ProjectsStorageService } from '../../services/projects-storage.service';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { NgIf, NgStyle } from '@angular/common';
import { LlmModelSelectorComponent } from '../../../../shared/components/llm-model-selector/llm-model-selector.component';
import { EmbeddingModelSelectorComponent } from '../../../../shared/components/embedding-model-selector/embedding-model-selector.component';
import { EmbeddingModelItemComponent } from '../../../../shared/components/embedding-model-selector/embedding-model-item/embedding-model-item.component';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { FormSliderComponent } from '../../../../shared/components/form-controls/slider/form-slider.component';
import { ToggleSwitchComponent } from '../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { ProcessSelectorComponent } from '../process-selector/process-selector.component';

@Component({
  selector: 'app-create-project',
  standalone: true,
  templateUrl: './create-project.component.html',
  styleUrls: ['./create-project.component.scss'],
  imports: [
    DialogModule,

    HelpTooltipComponent,
    ReactiveFormsModule,
    FormSliderComponent,
    ProcessSelectorComponent,

    ToggleSwitchComponent,
    LlmModelSelectorComponent,
    EmbeddingModelSelectorComponent,
    IconButtonComponent,
    NgIf,

    AppIconComponent,
  ],
})
export class CreateProjectComponent implements OnInit, OnDestroy {
  public projectForm: FormGroup;
  public sliderValue = 0;
  public maxRpmSliderValue = 15;
  public activeTab: 'overview' | 'configurations' = 'overview';

  public llmConfigs: FullLLMConfig[] = [];
  public embeddingConfigs: FullEmbeddingConfig[] = [];

  public selectedIcon: string | null = 'star';

  public get activeColor(): string {
    return '#685fff';
  }

  private destroy$ = new Subject<void>();

  public isSubmitting = false;

  constructor(
    private fb: FormBuilder,
    private dialogRef: DialogRef<GetProjectRequest | undefined>,
    private fullLlmConfigService: FullLLMConfigService,
    private fullEmbeddingConfigService: FullEmbeddingConfigService,
    private projectsService: ProjectsStorageService,
    private toastService: ToastService
  ) {
    this.projectForm = this.fb.group({
      name: ['', Validators.required],
      description: [''],
      process_type: ['sequential'],
      manager_llm_config: [null],
      memory_llm_config: [null],
      embedding_config: [null],
      planning_llm_config: [null],
      default_temperature: [0],
      memory: [false],
      cache: [true],
      full_output: [true],
      planning: [false],
      project_icon: ['ui/star'],

      tasks: [[]],
      agents: [[]],
      config: [null],
      max_rpm: [15],
    });
  }

  public ngOnInit(): void {
    // Fetch LLM configs using service
    this.fullLlmConfigService
      .getFullLLMConfigs()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (configs) => {
          this.llmConfigs = configs;
        },
        error: (error) => {
          console.error('Error fetching LLM configs:', error);
        },
      });

    // Fetch embedding configs using service
    this.fullEmbeddingConfigService
      .getFullEmbeddingConfigs()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (configs) => {
          this.embeddingConfigs = configs;
        },
        error: (error) => {
          console.error('Error fetching embedding configs:', error);
        },
      });

    // Setup dynamic validation
    this.setupDynamicValidation();
  }

  private setupDynamicValidation(): void {
    // Watch for changes in memory toggle
    this.projectForm
      .get('memory')
      ?.valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((memoryEnabled: boolean) => {
        const memoryLlmControl = this.projectForm.get('memory_llm_config');
        const embeddingControl = this.projectForm.get('embedding_config');

        if (memoryEnabled) {
          // Add required validators when memory is enabled
          memoryLlmControl?.setValidators([Validators.required]);
          embeddingControl?.setValidators([Validators.required]);
        } else {
          // Remove validators when memory is disabled
          memoryLlmControl?.clearValidators();
          embeddingControl?.clearValidators();
        }

        // Update validation status
        memoryLlmControl?.updateValueAndValidity();
        embeddingControl?.updateValueAndValidity();
      });

    // Watch for changes in process type
    this.projectForm
      .get('process_type')
      ?.valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((processType: string) => {
        const managerLlmControl = this.projectForm.get('manager_llm_config');

        if (processType === 'hierarchical') {
          // Add required validator when hierarchical is selected
          managerLlmControl?.setValidators([Validators.required]);
        } else {
          // Remove validator when sequential is selected
          managerLlmControl?.clearValidators();
        }

        // Update validation status
        managerLlmControl?.updateValueAndValidity();
      });

    // Trigger initial validation based on current values
    const currentMemory = this.projectForm.get('memory')?.value;
    const currentProcessType = this.projectForm.get('process_type')?.value;

    if (currentMemory) {
      this.projectForm
        .get('memory_llm_config')
        ?.setValidators([Validators.required]);
      this.projectForm
        .get('embedding_config')
        ?.setValidators([Validators.required]);
    }

    if (currentProcessType === 'hierarchical') {
      this.projectForm
        .get('manager_llm_config')
        ?.setValidators([Validators.required]);
    }

    // Update all validations
    this.projectForm.get('memory_llm_config')?.updateValueAndValidity();
    this.projectForm.get('embedding_config')?.updateValueAndValidity();
    this.projectForm.get('manager_llm_config')?.updateValueAndValidity();
  }

  public ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  public switchTab(tab: 'overview' | 'configurations'): void {
    this.activeTab = tab;
  }

  public setProcessType(type: 'sequential' | 'hierarchical'): void {
    this.projectForm.get('process_type')?.setValue(type);
  }

  public onManagerLLMChange(value: number | null): void {
    console.log('Selected Manager LLM Config ID:', value);
    this.projectForm.get('manager_llm_config')?.setValue(value);
  }

  public onMemoryLLMChange(value: number | null): void {
    console.log('Selected Memory LLM Config ID:', value);
    this.projectForm.get('memory_llm_config')?.setValue(value);
  }

  public onEmbeddingChange(value: number | null): void {
    console.log('Selected Embedding Config ID:', value);
    this.projectForm.get('embedding_config')?.setValue(value);
  }

  public onSliderInput(newValue: number): void {
    this.sliderValue = newValue;
    this.projectForm.get('default_temperature')?.setValue(newValue / 100);
  }

  public onMaxRpmSliderInput(newValue: number): void {
    this.maxRpmSliderValue = newValue;
    this.projectForm.get('max_rpm')?.setValue(newValue);
  }

  // Updated onCancelForm method to just close the dialog
  public onCancelForm(): void {
    this.dialogRef.close(undefined);
  }

  public onSubmitForm(): void {
    if (this.projectForm.valid) {
      this.isSubmitting = true;
      // Convert slider value (0-100) to temperature value (0-1)
      const temperatureValue = this.sliderValue / 100;

      // Construct the project request
      const projectRequest: CreateProjectRequest = {
        // Basic info
        name: this.projectForm.get('name')?.value,
        description: this.projectForm.get('description')?.value || null,

        // Process type (must be 'sequential' or 'hierarchical')
        process: this.projectForm.get('process_type')?.value,

        // Optional config fields
        memory: this.projectForm.get('memory')?.value,
        cache: this.projectForm.get('cache')?.value,
        full_output: this.projectForm.get('full_output')?.value,
        planning: this.projectForm.get('planning')?.value,

        // Temperature (normalized from slider)
        default_temperature: temperatureValue,

        // Configuration-related fields
        manager_llm_config: this.projectForm.get('manager_llm_config')?.value,
        memory_llm_config: this.projectForm.get('memory_llm_config')?.value,
        embedding_config: this.projectForm.get('embedding_config')?.value,
        planning_llm_config: this.projectForm.get('planning_llm_config')?.value,

        // Additional fields
        tasks: this.projectForm.get('tasks')?.value,
        agents: this.projectForm.get('agents')?.value,
        config: this.projectForm.get('config')?.value,
        max_rpm: this.projectForm.get('max_rpm')?.value,

        // Icon metadata
        metadata: {
          icon: this.projectForm.get('project_icon')?.value || 'ui/star',
        },
      };

      console.log('Submitting project data:', projectRequest);

      // Send the create project request using ProjectsService
      this.projectsService.createProject(projectRequest).subscribe({
        next: (project: GetProjectRequest) => {
          console.log('Project created successfully:', project);
          this.isSubmitting = false;
          this.toastService.success(
            `Project "${project.name}" created successfully!`
          );

          this.dialogRef.close(project);
        },
        error: (error) => {
          this.isSubmitting = false;

          console.error('Error creating project:', error);

          this.toastService.error(
            `Failed to delete project: ${error.message || 'Unknown error'}`
          );
        },
      });
    } else {
      // Mark all form controls as touched to show validation errors
      this.markFormGroupTouched(this.projectForm);
    }
  }

  private markFormGroupTouched(formGroup: FormGroup): void {
    Object.values(formGroup.controls).forEach((control) => {
      control.markAsTouched();
      if (control instanceof FormGroup) {
        this.markFormGroupTouched(control);
      }
    });
  }
}

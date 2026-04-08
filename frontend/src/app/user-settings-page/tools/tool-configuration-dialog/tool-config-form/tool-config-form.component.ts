import { NgFor, NgIf, NgSwitch, NgSwitchCase, NgSwitchDefault } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnChanges,
    OnInit,
    Output,
    SimpleChanges,
} from '@angular/core';
import {
    AbstractControl,
    FormBuilder,
    FormGroup,
    ReactiveFormsModule,
    ValidationErrors,
    ValidatorFn,
    Validators,
} from '@angular/forms';

import { FullEmbeddingConfig } from '../../../../features/settings-dialog/services/embeddings/full-embedding.service';
import { FullLLMConfig } from '../../../../features/settings-dialog/services/llms/full-llm-config.service';
import { Tool } from '../../../../features/tools/models/tool.model';
import { CreateToolConfigRequest, ToolConfig } from '../../../../features/tools/models/tool-config.model';
import { ToolConfigService } from '../../../../features/tools/services/tool-config.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { EmbeddingModelSelectorComponent } from '../../../../shared/components/embedding-model-selector/embedding-model-selector.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { LlmModelSelectorComponent } from '../../../../shared/components/llm-model-selector/llm-model-selector.component';

@Component({
    selector: 'app-tool-config-form',
    templateUrl: './tool-config-form.component.html',
    styleUrls: ['./tool-config-form.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ReactiveFormsModule,
        NgIf,
        NgFor,
        NgSwitch,
        NgSwitchCase,
        NgSwitchDefault,
        HelpTooltipComponent,
        LlmModelSelectorComponent,
        EmbeddingModelSelectorComponent,
    ],
})
export class ToolConfigFormComponent implements OnInit, OnChanges {
    @Input({ required: true }) llmConfigs!: FullLLMConfig[];
    @Input({ required: true }) embeddingConfigs!: FullEmbeddingConfig[];
    @Input({ required: true }) existingToolConfigs!: ToolConfig[];
    @Input({ required: true }) tool!: Tool;
    @Input() selectedConfig: ToolConfig | null = null;

    @Output() submitForm = new EventEmitter<ToolConfig>();
    @Output() cancelForm = new EventEmitter<void>();

    public form!: FormGroup;

    constructor(
        private fb: FormBuilder,
        private cdr: ChangeDetectorRef,
        private toolConfigService: ToolConfigService,
        private toastService: ToastService
    ) {}

    ngOnInit(): void {
        this.buildForm();
        if (this.selectedConfig) {
            this.populateFormWithConfig(this.selectedConfig);
        }
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['selectedConfig']) {
            // Make sure form is built first if it doesn't exist
            if (!this.form) {
                this.buildForm();
            }

            if (this.selectedConfig) {
                // Edit mode
                this.populateFormWithConfig(this.selectedConfig);
            } else {
                // Create mode - reset the form
                this.buildForm();
            }
        }
    }
    buildForm(): void {
        this.form = this.fb.group({
            name: ['', [Validators.required, Validators.minLength(3), this.uniqueNameValidator()]],
        });

        this.tool.tool_fields.forEach((field) => {
            const validators = field.required ? [Validators.required] : [];
            switch (field.data_type) {
                case 'llm_config':
                    // Handle LLM config field - should be a dropdown with LLM configs
                    this.form.addControl(field.name, this.fb.control('', validators));
                    break;
                case 'embedding_config':
                    // Handle embedding config field - should be a dropdown with embedding configs
                    this.form.addControl(field.name, this.fb.control('', validators));
                    break;
                case 'string':
                case 'any':
                    this.form.addControl(field.name, this.fb.control('', validators));
                    break;
                case 'boolean':
                    this.form.addControl(field.name, this.fb.control(false, validators));
                    break;
                case 'integer':
                    const intValidators = field.required
                        ? [Validators.required, this.integerValidator()]
                        : [this.integerValidator()];
                    this.form.addControl(field.name, this.fb.control('', intValidators));
                    break;
                default:
                    console.warn(`Unhandled data type: ${field.data_type}`);
            }
        });
    }

    populateFormWithConfig(config: ToolConfig): void {
        // Make sure form and config exist before proceeding
        if (!this.form || !config || !config.configuration) {
            console.warn('Form or config is not initialized in populateFormWithConfig');
            return;
        }

        try {
            const formData: Record<string, unknown> = { name: config.name };
            for (const key in config.configuration) {
                if (config.configuration.hasOwnProperty(key)) {
                    formData[key] = config.configuration[key];
                }
            }
            this.form.patchValue(formData);

            // After patching, check for llm_config and embedding_config fields that are null
            this.tool.tool_fields.forEach((field) => {
                if (
                    (field.data_type === 'llm_config' || field.data_type === 'embedding_config') &&
                    this.form.controls[field.name]
                ) {
                    const control = this.form.get(field.name);
                    if (control) {
                        if (control.value === null) {
                            // Set to empty string so required validator fails
                            control.setValue('');
                        } else {
                            // Ensure LLM config and embedding config values are numbers
                            // This handles cases where they might be stored as strings
                            const numValue = Number(control.value);
                            if (!isNaN(numValue)) {
                                control.setValue(numValue);
                            }
                        }

                        // Mark the control as touched or dirty so errors appear immediately
                        control.markAsTouched();
                        control.updateValueAndValidity(); // Re-run validation
                    }
                }
            });
        } catch (error) {
            console.error('Error in populateFormWithConfig:', error);
            this.toastService.error(`Error loading configuration: ${error}`);
        }
    }

    private uniqueNameValidator(): ValidatorFn {
        return (control: AbstractControl): ValidationErrors | null => {
            const currentName = control.value?.trim().toLowerCase();
            if (!currentName) return null;

            // If editing, allow the same name as the selected config
            const nameExists: boolean = this.existingToolConfigs.some((config) => {
                const configName = config.name.trim().toLowerCase();
                // If in edit mode, ignore the currently selected config
                if (this.selectedConfig && config.id === this.selectedConfig.id) {
                    return false;
                }
                return configName === currentName;
            });

            return nameExists ? { nonUniqueName: true } : null;
        };
    }
    // Custom integer validator
    private integerValidator(): ValidatorFn {
        return (control: AbstractControl): ValidationErrors | null => {
            const value = control.value;
            // Allow empty or null if not required
            if (value === '' || value === null) {
                return null;
            }

            // Check if the value is an integer
            const parsed = Number(value);
            if (!Number.isInteger(parsed)) {
                return { notInteger: true };
            }

            return null;
        };
    }

    onSubmit(): void {
        if (this.form.valid) {
            const formData = this.form.value;

            const configuration: { [key: string]: unknown } = {};

            // Loop over all form controls except 'name'
            for (const key in formData) {
                if (formData.hasOwnProperty(key) && key !== 'name') {
                    // Find the corresponding field definition
                    const field = this.tool.tool_fields.find((f) => f.name === key);

                    if (field) {
                        let value = formData[key];

                        // Convert based on field type
                        switch (field.data_type) {
                            case 'integer':
                            case 'embedding_config':
                            case 'llm_config':
                                // Convert to number if not empty or null
                                value = value !== null && value !== '' ? Number(value) : null;
                                break;
                            case 'boolean':
                                // Convert string 'true'/'false' to actual boolean
                                value = value === 'true' || value === true;
                                break;
                            default:
                                value = String(value);
                                break;
                        }

                        // Only add to configuration if value is not empty string
                        if (value !== '') {
                            configuration[key] = value;
                        }
                    } else {
                        // If field not found, default to string and check
                        const val = String(formData[key]);
                        if (val !== '') {
                            configuration[key] = val;
                        }
                    }
                }
            }

            const toolConfigRequest: CreateToolConfigRequest = {
                name: formData.name,
                configuration,
                tool: this.tool.id,
            };

            if (!this.selectedConfig) {
                // Create new configuration
                this.toolConfigService.createToolConfig(toolConfigRequest).subscribe({
                    next: (createdConfig) => {
                        this.submitForm.emit(createdConfig);
                        this.cdr.markForCheck();
                    },
                    error: (err) => {
                        console.error('Error creating configuration:', err);
                        this.toastService.error(`Failed to create configuration: ${err.message || 'Unknown error'}`);
                    },
                });
            } else {
                // Update existing configuration
                this.toolConfigService.updateToolConfig(this.selectedConfig.id, toolConfigRequest).subscribe({
                    next: (updatedConfig) => {
                        this.submitForm.emit(updatedConfig); // Notify parent
                        this.cdr.markForCheck();
                    },
                    error: (err) => {
                        console.error('Error updating configuration:', err);
                        this.toastService.error(`Failed to update configuration: ${err.message || 'Unknown error'}`);
                    },
                });
            }
        } else {
            this.form.markAllAsTouched();
            this.toastService.warning('Please fix the validation errors before submitting the form.');
        }
    }

    onCancel(): void {
        this.cancelForm.emit();
    }
}

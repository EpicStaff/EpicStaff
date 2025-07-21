import { Component, Inject, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { LLM_Provider } from '../../../../../features/settings-dialog/models/LLM_provider.model';
import { GetLlmModelRequest } from '../../../../../features/settings-dialog/models/llms/LLM.model';
import { FullLLMConfig } from '../../../../../features/settings-dialog/services/llms/full-llm-config.service';
import { ToastService } from '../../../../../services/notifications/toast.service';
import { LLM_Config_Service } from '../../../../../features/settings-dialog/services/llms/LLM_config.service';
import { CreateLLMConfigRequest } from '../../../../../features/settings-dialog/models/llms/LLM_config.model';

export interface AddLLMDialogData {
  provider: LLM_Provider;
  models: GetLlmModelRequest[];
}

@Component({
  selector: 'app-add-llm-dialog',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  template: `
    <div class="dialog-container">
      <div class="dialog-header">
        <h2 class="dialog-title">
          Create an LLM for {{ data.provider.name.toUpperCase() }}
        </h2>
        <button class="close-button" (click)="onCancel()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <line
              x1="18"
              y1="6"
              x2="6"
              y2="18"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            />
            <line
              x1="6"
              y1="6"
              x2="18"
              y2="18"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            />
          </svg>
        </button>
      </div>

      <div class="dialog-content">
        <form [formGroup]="llmForm">
          <div class="form-group">
            <label for="model">Model</label>
            <div class="custom-select">
              <select id="model" formControlName="model" class="select-input">
                <option value="" disabled>Select a model</option>
                @for (model of data.models; track model.id) {
                <option [value]="model.id">{{ model.name }}</option>
                }
              </select>
              <div class="select-arrow">
                <svg
                  width="10"
                  height="6"
                  viewBox="0 0 10 6"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M1 1L5 5L9 1"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </div>
            </div>
          </div>

          <div class="form-group">
            <label for="customName">Custom Name</label>
            <input
              type="text"
              id="customName"
              formControlName="customName"
              placeholder="Enter a custom name"
              class="text-input"
            />
          </div>

          <div class="form-group">
            <label for="apiKey">API Key</label>
            <div class="input-with-icon">
              <input
                type="text"
                id="apiKey"
                formControlName="apiKey"
                placeholder="Enter API key"
                class="text-input"
              />
              <button
                type="button"
                class="eye-button"
                (click)="toggleApiKeyVisibility()"
              >
                @if (showApiKey) {
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M2 12C2 12 5 5 12 5C19 5 22 12 22 12C22 12 19 19 12 19C5 19 2 12 2 12Z"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                  <path
                    d="M12 15C13.6569 15 15 13.6569 15 12C15 10.3431 13.6569 9 12 9C10.3431 9 9 10.3431 9 12C9 13.6569 10.3431 15 12 15Z"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                  <path
                    d="M3 3L21 21"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
                } @else {
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M2 12C2 12 5 5 12 5C19 5 22 12 22 12C22 12 19 19 12 19C5 19 2 12 2 12Z"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                  <path
                    d="M12 15C13.6569 15 15 13.6569 15 12C15 10.3431 13.6569 9 12 9C10.3431 9 9 10.3431 9 12C9 13.6569 10.3431 15 12 15Z"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
                }
              </button>
            </div>
          </div>
        </form>
      </div>

      <div class="dialog-footer">
        <button class="button secondary" (click)="onCancel()">Cancel</button>
        <button
          class="button primary"
          [disabled]="llmForm.invalid"
          (click)="onConfirm()"
        >
          Create
        </button>
      </div>
    </div>
  `,
  styles: [
    `
      .dialog-container {
        background-color: #1e1e1e;
        border-radius: 12px;
        padding: 24px;
        color: rgba(255, 255, 255, 0.9);
        min-width: 400px;
      }

      .dialog-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;

        .dialog-title {
          margin: 0;
          font-size: 18px;
          font-weight: 600;
        }

        .close-button {
          background: none;
          border: none;
          color: rgba(255, 255, 255, 0.6);
          cursor: pointer;
          padding: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 4px;
          margin-left: 10px;
          &:hover {
            background-color: rgba(255, 255, 255, 0.1);
            color: rgba(255, 255, 255, 0.9);
          }
        }
      }

      .dialog-content {
        margin-bottom: 24px;
      }

      .form-group {
        margin-bottom: 16px;

        label {
          display: block;
          margin-bottom: 8px;
          font-size: 14px;
          color: rgba(255, 255, 255, 0.7);
        }

        .text-input {
          width: 100%;
          padding: 10px 12px;
          background-color: rgba(30, 30, 30, 0.6);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 6px;
          color: white;
          font-size: 14px;
          transition: border-color 0.2s ease;

          &:focus {
            outline: none;
            border-color: #685fff;
          }
        }

        .custom-select {
          position: relative;

          .select-input {
            width: 100%;
            padding: 10px 12px;
            background-color: rgba(30, 30, 30, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            color: white;
            font-size: 14px;
            appearance: none;
            transition: border-color 0.2s ease;

            &:focus {
              outline: none;
              border-color: #685fff;
            }
          }

          .select-arrow {
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            pointer-events: none;
            color: rgba(255, 255, 255, 0.6);
          }
        }

        .input-with-icon {
          position: relative;

          .text-input {
            padding-right: 40px;
          }

          .eye-button {
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            background: none;
            border: none;
            color: rgba(255, 255, 255, 0.6);
            cursor: pointer;
            padding: 4px;
            display: flex;
            align-items: center;
            justify-content: center;

            &:hover {
              color: rgba(255, 255, 255, 0.9);
            }
          }
        }

        .error-message {
          font-size: 12px;
          color: #ff4d4f;
          margin-top: 4px;
        }
      }

      .dialog-footer {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
      }

      .button {
        padding: 8px 16px;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: background-color 0.2s ease;
        border: none;

        &.secondary {
          background-color: rgba(255, 255, 255, 0.1);
          color: rgba(255, 255, 255, 0.9);

          &:hover {
            background-color: rgba(255, 255, 255, 0.15);
          }
        }

        &.primary {
          background-color: #685fff;
          color: white;

          &:hover {
            background-color: #7a70ff;
          }

          &:disabled {
            background-color: rgba(104, 95, 255, 0.5);
            cursor: not-allowed;
          }
        }
      }
    `,
  ],
})
export class AddLLMDialogComponent implements OnInit {
  llmForm!: FormGroup;
  showApiKey = false;
  private llmConfigService = inject(LLM_Config_Service);

  constructor(
    private fb: FormBuilder,
    public dialogRef: DialogRef<FullLLMConfig | undefined>,
    private toastService: ToastService,

    @Inject(DIALOG_DATA) public data: AddLLMDialogData
  ) {}

  ngOnInit(): void {
    this.initForm();
  }

  private initForm(): void {
    this.llmForm = this.fb.group({
      model: ['', Validators.required],
      customName: ['', Validators.required],
      apiKey: ['', Validators.required],
    });
  }

  showError(controlName: string): boolean {
    const control = this.llmForm.get(controlName);
    return control
      ? control.invalid && (control.touched || control.dirty)
      : false;
  }

  toggleApiKeyVisibility(): void {
    this.showApiKey = !this.showApiKey;
  }

  onConfirm(): void {
    if (this.llmForm.valid) {
      const formValue = this.llmForm.value;

      const modelId = Number(formValue.model);
      const config: CreateLLMConfigRequest = {
        model: modelId,
        custom_name: formValue.customName,
        api_key: formValue.apiKey,

        is_visible: true,
      };

      // Find the selected model details
      const modelDetails =
        this.data.models.find((model) => model.id === modelId) || null;

      // Create the LLM config through the service
      this.llmConfigService.createConfig(config).subscribe({
        next: (createdConfig) => {
          // Create a FullLLMConfig with the response and model details
          const fullConfig: FullLLMConfig = {
            ...createdConfig,
            modelDetails,
            providerDetails: this.data.provider,
          };
          this.toastService.success(
            `LLM "${fullConfig.custom_name}" has been successfully created`
          );
          // Close the dialog with the full config
          this.dialogRef.close(fullConfig);
        },
        error: (error) => {
          console.error('Error creating LLM config:', error);
          // You could handle errors here (e.g., show a message)
          // For now, we'll just keep the dialog open
        },
      });
    } else {
      // Mark all fields as touched to show validation errors
      this.llmForm.markAllAsTouched();
    }
  }

  onCancel(): void {
    this.dialogRef.close();
  }
}

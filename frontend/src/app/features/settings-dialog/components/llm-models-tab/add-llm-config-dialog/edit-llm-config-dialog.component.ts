import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatSliderModule } from '@angular/material/slider';

import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { UpdateLLMConfigRequest } from '../../../models/llms/LLM_config.model';
import { LLM_Config_Service } from '../../../services/llms/llm-config.service';

@Component({
    selector: 'app-edit-llm-config-dialog',
    standalone: true,
    imports: [CommonModule, ReactiveFormsModule, ButtonComponent, CustomInputComponent, MatSliderModule],
    templateUrl: './edit-llm-config-dialog.component.html',
    styleUrls: ['./edit-llm-config-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditLlmConfigDialogComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private formBuilder = inject(FormBuilder);
    private configService = inject(LLM_Config_Service);
    private readonly destroyRef = inject(DestroyRef);
    public form!: FormGroup;
    public isSubmitting = signal<boolean>(false);
    public errorMessage = signal<string | null>(null);
    public config = inject(DIALOG_DATA) as UpdateLLMConfigRequest;
    public showApiKey = signal<boolean>(false);

    get temperatureControl(): FormControl {
        return this.form.get('temperature') as FormControl;
    }

    ngOnInit(): void {
        this.form = this.formBuilder.group({
            customName: [this.config.custom_name, Validators.required],
            apiKey: [this.config.api_key, Validators.required],
            temperature: [Math.round((this.config.temperature ?? 0) * 100), [Validators.min(0), Validators.max(100)]],
        });

        this.dialogRef.keydownEvents
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(event => {
                if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                    event.preventDefault();
                    this.onSubmit();
                }
            });
    }

    public toggleApiKeyVisibility(): void {
        this.showApiKey.set(!this.showApiKey());
    }

    public onTemperatureChange(event: Event): void {
        const newValue = (event.target as HTMLInputElement).value || 0;
        this.temperatureControl.setValue(Number(newValue));
    }

    public onSubmit(): void {
        this.form.markAllAsTouched();
        if (this.form.invalid) return;
        this.isSubmitting.set(true);
        const formValue = this.form.value;
        const updateReq: UpdateLLMConfigRequest = {
            ...this.config,
            custom_name: formValue.customName,
            api_key: formValue.apiKey,
            temperature: formValue.temperature / 100,
        };
        this.configService.updateConfig(updateReq).subscribe({
            next: () => {
                this.dialogRef.close(true);
            },
            error: () => {
                this.errorMessage.set('Failed to update configuration. Please try again.');
                this.isSubmitting.set(false);
            },
        });
    }

    public onCancel(): void {
        this.dialogRef.close(false);
    }
}

import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { finalize } from 'rxjs/operators';

import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { UpdateRealtimeModelConfigRequest } from '../../../models/realtime-voice/realtime-llm-config.model';
import { FullRealtimeConfig } from '../../../services/realtime-llms/full-reamtime-config.service';
import { RealtimeModelConfigsService } from '../../../services/realtime-llms/real-time-model-config.service';

@Component({
    selector: 'app-edit-voice-config-dialog',
    standalone: true,
    imports: [CommonModule, ReactiveFormsModule, ButtonComponent, CustomInputComponent],
    templateUrl: './edit-voice-config-dialog.component.html',
    styleUrls: ['./edit-voice-config-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditVoiceConfigDialogComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private formBuilder = inject(FormBuilder);
    private configService = inject(RealtimeModelConfigsService);
    private dialogData = inject<FullRealtimeConfig>(DIALOG_DATA);
    private readonly destroyRef = inject(DestroyRef);

    public form!: FormGroup;
    public isSubmitting = signal<boolean>(false);
    public errorMessage = signal<string | null>(null);
    public showApiKey = signal<boolean>(false);

    ngOnInit(): void {
        this.initForm();

        this.dialogRef.keydownEvents
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(event => {
                if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                    event.preventDefault();
                    this.onSubmit();
                }
            });
    }

    private initForm(): void {
        this.form = this.formBuilder.group({
            customName: [this.dialogData.custom_name, Validators.required],
            apiKey: [this.dialogData.api_key, Validators.required],
        });
    }

    public toggleApiKeyVisibility(): void {
        this.showApiKey.set(!this.showApiKey());
    }

    public onSubmit(): void {
        this.form.markAllAsTouched();
        if (this.form.invalid) {
            return;
        }

        this.isSubmitting.set(true);
        const formValue = this.form.value;

        const configData: UpdateRealtimeModelConfigRequest = {
            id: this.dialogData.id,
            realtime_model: this.dialogData.realtime_model,
            custom_name: formValue.customName,
            api_key: formValue.apiKey,
        };

        this.configService
            .updateConfig(configData)
            .pipe(finalize(() => this.isSubmitting.set(false)))
            .subscribe({
                next: () => {
                    this.dialogRef.close(true); // Close with success result
                },
                error: () => {
                    this.errorMessage.set('Failed to update configuration. Please try again.');
                },
            });
    }

    public onCancel(): void {
        this.dialogRef.close(false);
    }
}

import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    IconButtonComponent,
    InputNumberComponent,
    JsonEditorFormFieldComponent,
    KeyValueListComponent,
    SliderWithStepperComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { LLMModel, LLMProvider, ModelTypes } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';

import { ToastService } from '../../../../services/notifications';
import { LlmModelSelectorComponent } from '../llm-model-selector/llm-model-selector.component';

interface DialogData {
    configId?: number;
}

@Component({
    selector: 'app-llm-model-config',
    templateUrl: './llm-model-config-dialog.component.html',
    styleUrls: ['./llm-model-config-dialog.component.scss'],
    imports: [
        IconButtonComponent,
        ButtonComponent,
        ReactiveFormsModule,
        CustomInputComponent,
        KeyValueListComponent,
        SliderWithStepperComponent,
        InputNumberComponent,
        ValidationErrorsComponent,
        LlmModelSelectorComponent,
        JsonEditorFormFieldComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelConfigDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);
    private configStorageService = inject(LlmConfigStorageService);
    private toast = inject(ToastService);
    private data = inject<DialogData>(DIALOG_DATA, { optional: true });

    dialogRef = inject(DialogRef);

    isSaving = signal<boolean>(false);
    isLoading = signal<boolean>(false);

    isEditMode = computed(() => !!this.data?.configId);
    title = computed(() => (this.isEditMode() ? 'Edit LLM Configuration' : 'Add LLM Configuration'));
    saveLabel = computed(() => (this.isEditMode() ? 'Save Changes' : 'Add LLM'));

    form!: FormGroup;

    ngOnInit() {
        this.form = this.fb.group({
            custom_name: ['', [Validators.required]],
            api_key: [''],
            model: [null, [Validators.required]],
            temperature: [0.5, [Validators.min(0), Validators.max(1)]],
            top_p: [1, [Validators.min(0.1)]],
            stop: [null],
            max_tokens: [4096, [Validators.min(500), Validators.max(2147483647)]],
            presence_penalty: [0],
            frequency_penalty: [0],
            logit_bias: [null],
            response_format: [null],
            seed: [null, [Validators.min(-2147483648), Validators.max(2147483647)]],
            headers: [{}],
            extra_headers: [{}],
            timeout: [120, [Validators.min(1), Validators.max(600)]],
            is_visible: [true],
        });

        if (this.data?.configId) {
            this.loadConfig(this.data.configId);
        }

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSave();
            }
        });
    }

    private loadConfig(configId: number): void {
        this.isLoading.set(true);
        this.configStorageService
            .getConfigById(configId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (config) => {
                    this.form.patchValue(config);
                    this.isLoading.set(false);
                },
                error: () => {
                    this.toast.error('Failed to load configuration.');
                    this.isLoading.set(false);
                },
            });
    }

    onModelChanged(data: { model: LLMModel; provider: LLMProvider }): void {
        const nameControl = this.form.get('custom_name');

        if (!nameControl) return;

        if (!nameControl.value) {
            nameControl.setValue(`${data.provider.name}/${data.model.name}`);
        }
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onSave(): void {
        if (this.form.invalid || this.isSaving() || this.isLoading()) {
            this.form.markAllAsTouched();
            return;
        }

        this.isSaving.set(true);
        const formValue = this.form.value;

        const request$ = this.isEditMode()
            ? this.configStorageService.updateConfig({ id: this.data!.configId!, ...formValue })
            : this.configStorageService.createConfig(formValue);

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => {
                this.isSaving.set(false);
                this.toast.success(
                    this.isEditMode() ? 'Configuration updated successfully.' : 'Configuration created successfully.'
                );
                this.dialogRef.close();
            },
            error: (err) => {
                this.isSaving.set(false);
                this.toast.error(this.isEditMode() ? 'Configuration update failed.' : 'Configuration creation failed.');
                console.error(err);
            },
        });
    }

    protected readonly ModelTypes = ModelTypes;
}

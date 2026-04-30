import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    IconButtonComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { LLMModel, LLMProvider, ModelTypes } from '@shared/models';
import { EmbeddingConfigStorageService } from '@shared/services';

import { ToastService } from '../../../../services/notifications';
import { LlmModelSelectorComponent } from '../llm-model-selector/llm-model-selector.component';

@Component({
    selector: 'app-embedding-config-model',
    templateUrl: './embedding-model-config-dialog.component.html',
    styleUrls: ['./embedding-model-config-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ButtonComponent,
        CustomInputComponent,
        IconButtonComponent,
        LlmModelSelectorComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
    ],
})
export class EmbeddingModelConfigDialogComponent {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);
    private embeddingConfigsService = inject(EmbeddingConfigStorageService);
    private toast = inject(ToastService);
    private data = inject(DIALOG_DATA, { optional: true });

    dialogRef = inject(DialogRef);

    isSaving = signal<boolean>(false);
    isLoading = signal<boolean>(false);

    isEditMode = computed(() => !!this.data?.configId);
    title = computed(() => (this.isEditMode() ? 'Edit Embedding Configuration' : 'Add Embedding Configuration'));
    saveLabel = computed(() => (this.isEditMode() ? 'Save Changes' : 'Add Embedding'));

    form!: FormGroup;

    ngOnInit() {
        this.form = this.fb.group({
            custom_name: ['', [Validators.required]],
            api_key: ['', [Validators.required]],
            model: [null, [Validators.required]],
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
        this.embeddingConfigsService
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
            ? this.embeddingConfigsService.updateConfig({ id: this.data!.configId!, ...formValue })
            : this.embeddingConfigsService.createConfig(formValue);

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

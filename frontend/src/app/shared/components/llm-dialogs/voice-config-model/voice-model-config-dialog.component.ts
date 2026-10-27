import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { EnterSubmitDirective } from '@shared/directives';
import { ModelTypes } from '@shared/models';
import { RealtimeConfigStorageService, SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage, isClientError, trackPickedSecrets } from '@shared/utils';

import { ToastService } from '../../../../services/notifications';
import { ValidationErrorsComponent } from '../../app-validation-errors/validation-errors.component';
import { BinnedSecretNoteComponent } from '../../binned-secret-note/binned-secret-note.component';
import { ButtonComponent, IconButtonComponent } from '../../buttons';
import { ErrorBannerComponent } from '../../error-banner/error-banner.component';
import { CustomInputComponent } from '../../form-input/form-input.component';
import { HintMessageComponent } from '../../hint-message/hint-message.component';
import { SelectComponent, SelectItem } from '../../select/select.component';
import { LlmModelSelectorComponent } from '../llm-model-selector/llm-model-selector.component';

@Component({
    selector: 'app-voice-config-model',
    templateUrl: './voice-model-config-dialog.component.html',
    styleUrls: ['./voice-model-config-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        BinnedSecretNoteComponent,
        ButtonComponent,
        CustomInputComponent,
        ErrorBannerComponent,
        IconButtonComponent,
        LlmModelSelectorComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
        SelectComponent,
        HintMessageComponent,
        EnterSubmitDirective,
    ],
})
export class VoiceModelConfigDialogComponent {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);
    private realtimeModelConfigsService = inject(RealtimeConfigStorageService);
    private secretsStorageService = inject(SecretsStorageService);
    private toast = inject(ToastService);
    private data = inject(DIALOG_DATA, { optional: true });

    dialogRef = inject(DialogRef);

    isSaving = signal<boolean>(false);
    isLoading = signal<boolean>(false);
    errorMessage = signal<string | null>(null);

    isEditMode = computed(() => !!this.data?.configId);
    title = computed(() => (this.isEditMode() ? 'Edit Voice Configuration' : 'Add Voice Configuration'));
    saveLabel = computed(() => (this.isEditMode() ? 'Save Changes' : 'Add Voice Model'));

    /** Secret ids picked in this form: a picked secret in the recycle bin keeps its option. */
    private readonly pickedSecretIds = signal<number[]>([]);
    secretItems = computed<SelectItem[]>(() => this.secretsStorageService.selectItems(this.pickedSecretIds()));

    form!: FormGroup;

    ngOnInit() {
        this.form = this.fb.group({
            custom_name: ['', [Validators.required]],
            api_key_secret_id: [null, [Validators.required]],
            realtime_model: [null, [Validators.required]],
        });
        trackPickedSecrets(this.form, ['api_key_secret_id'], this.pickedSecretIds, this.destroyRef);

        if (this.data?.configId) {
            this.loadConfig(this.data.configId);
        }

        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => this.toast.error('Failed to load secrets.'),
            });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSave();
            }
        });
    }

    private loadConfig(configId: number): void {
        this.isLoading.set(true);
        this.realtimeModelConfigsService
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

    onCancel(): void {
        this.dialogRef.close();
    }

    onSave(): void {
        if (this.form.invalid || this.isSaving() || this.isLoading()) {
            this.form.markAllAsTouched();
            return;
        }

        this.isSaving.set(true);
        this.errorMessage.set(null);
        const formValue = this.form.value;

        const request$ = this.isEditMode()
            ? this.realtimeModelConfigsService.updateConfig({ id: this.data!.configId!, ...formValue })
            : this.realtimeModelConfigsService.createConfig(formValue);

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => {
                this.isSaving.set(false);
                this.toast.success(
                    this.isEditMode() ? 'Configuration updated successfully.' : 'Configuration created successfully.'
                );
                this.dialogRef.close();
            },
            error: (err: HttpErrorResponse) => {
                this.isSaving.set(false);
                const fallback = this.isEditMode() ? 'Configuration update failed.' : 'Configuration creation failed.';
                if (isClientError(err)) {
                    this.errorMessage.set(extractHttpErrorMessage(err, fallback));
                    return;
                }
                this.toast.error(fallback);
                console.error(err);
            },
        });
    }

    protected readonly ModelTypes = ModelTypes;
}

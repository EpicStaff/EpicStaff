import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgIf } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { CreateNgrokConfigRequest, GetNgrokConfigResponse } from '@shared/models';
import { NgrokConfigStorageService, SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';

@Component({
    selector: 'app-create-ngrok-config-dialog',
    templateUrl: './add-ngrok-config-dialog.component.html',
    styleUrls: ['./add-ngrok-config-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        SelectComponent,
        ButtonComponent,
        ValidationErrorsComponent,
        NgIf,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddNgrokConfigDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private dialogRef = inject(DialogRef);
    private ngrokStorageService = inject(NgrokConfigStorageService);
    private secretsStorageService = inject(SecretsStorageService);
    private destroyRef = inject(DestroyRef);
    data: { config: GetNgrokConfigResponse | null; action: 'create' | 'update' } = inject(DIALOG_DATA);

    public isSubmitting = signal<boolean>(false);
    public errorMessage = signal<string | null>(null);

    // TODO: NgrokWebhookConfig.auth_token is still a plain CharField on the backend (no
    // api_key_secret-style ForeignKey to Secret yet, unlike LLMConfig/RealtimeConfig). Until
    // that lands, this select submits the chosen secret's numeric id as auth_token, which the
    // backend will store as a literal string — not a working token. Frontend-only for now.
    secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );

    form!: FormGroup;
    regionSelectItems: SelectItem[] = [
        {
            name: 'EU',
            value: 'eu',
        },
        {
            name: 'US',
            value: 'us',
        },
        {
            name: 'AP',
            value: 'ap',
        },
    ];

    ngOnInit() {
        this.initForm();

        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => this.errorMessage.set('Failed to load secrets.'),
            });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSubmit();
            }
        });
    }

    private initForm(): void {
        this.form = this.fb.group({
            name: [this.data.config?.name || '', Validators.required],
            auth_token: [this.data.config?.auth_token || '', Validators.required],
            region: [this.data.config?.region || 'eu'],
            domain: [this.data.config?.domain || ''],
        });
    }

    onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        this.isSubmitting.set(true);

        const formValue = this.form.value;
        const { config, action } = this.data;

        if (action === 'create') {
            this.createNgrokConfig(formValue);
        } else {
            this.updateNgrokConfig(config!.id, formValue);
        }
    }

    private createNgrokConfig(value: CreateNgrokConfigRequest): void {
        this.ngrokStorageService
            .createConfig(value)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.dialogRef.close(),
                error: (err: HttpErrorResponse) => {
                    this.errorMessage.set(extractHttpErrorMessage(err));
                    this.isSubmitting.set(false);
                },
            });
    }

    private updateNgrokConfig(id: number, value: CreateNgrokConfigRequest): void {
        this.ngrokStorageService
            .updateConfigById(id, value)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.dialogRef.close(),
                error: (err: HttpErrorResponse) => {
                    this.errorMessage.set(extractHttpErrorMessage(err));
                    this.isSubmitting.set(false);
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close();
    }
}

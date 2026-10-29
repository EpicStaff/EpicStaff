import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { EnterSubmitDirective } from '@shared/directives';
import { WebhookTriggerModel } from '@shared/models';
import { extractHttpErrorMessage, isClientError } from '@shared/utils';

import { WebhookTriggerService } from '../../services/webhook-trigger/webhook-trigger.service';
import { ButtonComponent } from '../buttons';
import { ErrorBannerComponent } from '../error-banner/error-banner.component';
import { WebhookTriggerFieldComponent } from '../webhook-trigger-field/webhook-trigger-field.component';

export interface WebhookTriggerDialogData {
    trigger: WebhookTriggerModel | null;
    /** Shows the trigger without letting it be saved: the user may not edit it (see the banner in the dialog). */
    readonly?: boolean;
}

@Component({
    selector: 'app-webhook-trigger-dialog',
    templateUrl: './webhook-trigger-dialog.component.html',
    styleUrls: ['./webhook-trigger-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        ButtonComponent,
        ErrorBannerComponent,
        WebhookTriggerFieldComponent,
        EnterSubmitDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private dialogRef = inject(DialogRef<WebhookTriggerModel | null>);
    private service = inject(WebhookTriggerService);
    private destroyRef = inject(DestroyRef);

    data: WebhookTriggerDialogData = inject(DIALOG_DATA);
    protected readonly isReadonly = this.data.readonly ?? false;

    isSubmitting = signal(false);
    errorMessage = signal<string | null>(null);

    form!: FormGroup;

    ngOnInit(): void {
        this.form = this.fb.group({
            webhook_trigger: [this.data.trigger ?? null],
        });
    }

    get isEdit(): boolean {
        return !!this.data.trigger?.id;
    }

    onSubmit(): void {
        if (this.isReadonly) return;
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        const trigger = this.form.value.webhook_trigger as WebhookTriggerModel | null;
        if (!trigger) {
            return;
        }

        this.isSubmitting.set(true);
        this.errorMessage.set(null);

        const request$ = trigger.id ? this.service.update(trigger.id, trigger) : this.service.create(trigger);

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (saved) => this.dialogRef.close(saved),
            error: (err: HttpErrorResponse) => {
                const fallback = 'Failed to save webhook trigger.';
                this.errorMessage.set(isClientError(err) ? extractHttpErrorMessage(err, fallback) : fallback);
                this.isSubmitting.set(false);
            },
        });
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}

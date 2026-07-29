import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';

import { WebhookTriggerModel } from '../../../visual-programming/core/models/webhook-trigger.model';
import { WebhookTriggerService } from '../../services/webhook-trigger/webhook-trigger.service';
import { ButtonComponent } from '../buttons';
import { WebhookTriggerFieldComponent } from '../webhook-trigger-field/webhook-trigger-field.component';

export interface WebhookTriggerDialogData {
    trigger: WebhookTriggerModel | null;
}

@Component({
    selector: 'app-webhook-trigger-dialog',
    templateUrl: './webhook-trigger-dialog.component.html',
    styleUrls: ['./webhook-trigger-dialog.component.scss'],
    imports: [ReactiveFormsModule, ButtonComponent, WebhookTriggerFieldComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private dialogRef = inject(DialogRef<WebhookTriggerModel | null>);
    private service = inject(WebhookTriggerService);
    private destroyRef = inject(DestroyRef);

    data: WebhookTriggerDialogData = inject(DIALOG_DATA);

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
                this.errorMessage.set(this.formatBackendError(err) ?? 'Failed to save webhook trigger.');
                this.isSubmitting.set(false);
            },
        });
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }

    private formatBackendError(err: HttpErrorResponse): string | null {
        const body = err?.error;
        if (!body) return null;
        if (typeof body === 'string') return body;
        if (typeof body.detail === 'string') return body.detail;
        if (typeof body === 'object') {
            const parts: string[] = [];
            for (const [field, value] of Object.entries(body)) {
                const text = Array.isArray(value) ? value.join(' ') : typeof value === 'string' ? value : null;
                if (text) parts.push(field === 'non_field_errors' ? text : `${field}: ${text}`);
            }
            if (parts.length) return parts.join(' • ');
        }
        return null;
    }
}

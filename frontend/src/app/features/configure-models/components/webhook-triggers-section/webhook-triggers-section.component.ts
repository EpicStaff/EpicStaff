import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ButtonComponent,
    ConfirmationDialogService,
    LoadingSpinnerComponent,
    WebhookTriggerDialogComponent,
    WebhookTriggerDialogData,
} from '@shared/components';
import { WebhookTriggerService } from '@shared/services';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { ToastService } from '../../../../services/notifications';
import { WebhookTriggerModel } from '../../../../visual-programming/core/models/webhook-trigger.model';

@Component({
    selector: 'app-webhook-triggers-section',
    templateUrl: './webhook-triggers-section.component.html',
    styleUrls: ['./webhook-triggers-section.component.scss'],
    imports: [ButtonComponent, LoadingSpinnerComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggersSectionComponent implements OnInit {
    private service = inject(WebhookTriggerService);
    private dialog = inject(Dialog);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    status = signal<LoadingState>(LoadingState.IDLE);
    triggers = signal<WebhookTriggerModel[]>([]);

    displayedTriggers = computed(() => this.triggers().map((t) => ({ ...t, name: this.getTriggerName(t) })));

    private getTriggerName(t: WebhookTriggerModel): string | undefined {
        switch (t.provider_type) {
            case 'ngrok':
                return t.ngrok_config?.name;
            case 'localhost':
                return t.localhost_config?.name;
            default:
                return;
        }
    }

    ngOnInit(): void {
        this.loadTriggers();
        this.service.changed$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.refresh());
    }

    private loadTriggers(): void {
        this.status.set(LoadingState.LOADING);
        this.service
            .list()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (triggers) => {
                    this.triggers.set(triggers);
                    this.status.set(LoadingState.LOADED);
                },
                error: () => this.status.set(LoadingState.ERROR),
            });
    }

    private refresh(): void {
        this.service
            .list()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ next: (triggers) => this.triggers.set(triggers), error: () => {} });
    }

    onAdd(): void {
        this.openDialog(null);
    }

    onEdit(trigger: WebhookTriggerModel): void {
        this.openDialog(trigger);
    }

    private openDialog(trigger: WebhookTriggerModel | null): void {
        this.dialog
            .open<WebhookTriggerModel | null, WebhookTriggerDialogData>(WebhookTriggerDialogComponent, {
                disableClose: true,
                data: { trigger },
            })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((saved) => {
                if (saved) this.refresh();
            });
    }

    onDelete(trigger: WebhookTriggerModel): void {
        if (trigger.id == null) return;
        const id = trigger.id;
        this.confirmationDialogService
            .confirmDelete(trigger.path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result !== true) return;
                this.service
                    .delete(id)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => {
                            this.triggers.update((list) => list.filter((t) => t.id !== id));
                            this.toastService.success(`Webhook trigger "${trigger.path}" deleted`);
                        },
                        error: () => this.toastService.error('Failed to delete webhook trigger'),
                    });
            });
    }
}

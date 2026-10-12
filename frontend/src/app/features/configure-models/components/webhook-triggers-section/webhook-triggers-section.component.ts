import { Dialog } from '@angular/cdk/dialog';
import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AuthorshipDetailsDialogService,
    AuthorshipDetailsSource,
    ButtonComponent,
    ConfirmationDialogService,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    WebhookTriggerDialogComponent,
    WebhookTriggerDialogData,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode, WebhookTriggerModel } from '@shared/models';
import { WebhookTriggerService } from '@shared/services';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { ToastService } from '../../../../services/notifications';

@Component({
    selector: 'app-webhook-triggers-section',
    templateUrl: './webhook-triggers-section.component.html',
    styleUrls: ['./webhook-triggers-section.component.scss'],
    imports: [
        ButtonComponent,
        LoadingSpinnerComponent,
        HasPermissionDirective,
        FetchErrorStateComponent,
        CdkMenuTrigger,
        CdkMenu,
        CdkMenuItem,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggersSectionComponent implements OnInit {
    private service = inject(WebhookTriggerService);
    private dialog = inject(Dialog);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    status = signal<LoadingState>(LoadingState.IDLE);
    triggers = signal<WebhookTriggerModel[]>([]);

    displayedTriggers = computed(() => this.triggers().map((t) => ({ ...t, name: this.getTriggerName(t) })));

    // Below the ⋮ button, right edges aligned; flips above when there is no room.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

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

    retry(): void {
        this.loadTriggers();
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

    /**
     * The menu item closes the menu itself once this returns, focusing its trigger; the details
     * dialog has already recorded the focused menu item by then, so it is told to close back to
     * the ⋮ button instead.
     */
    protected onViewDetails(trigger: WebhookTriggerModel, menuTriggerButton: HTMLElement): void {
        this.authorshipDetailsDialog.open(
            'Webhook Trigger Details',
            this.toAuthorshipSource(trigger),
            menuTriggerButton
        );
    }

    /**
     * Escape must close only the menu, not the Configure Models dialog under it: CdkMenu lets
     * Escape bubble on to the overlay keyboard dispatcher after destroying the menu view, so the
     * focused item intercepts it first and closes the menu the way CdkMenu would.
     */
    protected onMenuItemEscape(event: Event, menuTrigger: CdkMenuTrigger, menuTriggerButton: HTMLElement): void {
        event.stopPropagation();
        menuTrigger.close();
        menuTriggerButton.focus();
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

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    // The model doubles as a form value, so its authorship fields are optional; a trigger loaded
    // from the API always carries them. Any that are absent render as the dialog's "unknown".
    private toAuthorshipSource(trigger: WebhookTriggerModel): AuthorshipDetailsSource {
        return {
            created_by: trigger.created_by ?? null,
            created_at: trigger.created_at ?? null,
            last_edited_by: trigger.last_edited_by ?? null,
            last_edited_at: trigger.last_edited_at ?? null,
        };
    }
}

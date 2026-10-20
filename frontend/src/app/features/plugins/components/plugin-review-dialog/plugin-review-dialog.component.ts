import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, LoadingSpinnerComponent } from '@shared/components';
import { finalize } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PackageReview, PluginDetail } from '../../models/plugin-admin.model';
import { PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginApproveRequest, PluginReviewPanelComponent } from '../plugin-review-panel/plugin-review-panel.component';

/** The review to show, or the package whose review to load. */
export type PluginReviewDialogData = { review: PackageReview } | { packageId: number };

export type PluginReviewDialogResult = { kind: 'approved'; plugin: PluginDetail } | { kind: 'rejected' };

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_REVIEW_DIALOG_TITLE_ID = 'plugin-review-dialog-title';

/** A package's review with Approve and Reject: after an upload, or for a plugin still waiting for approval. */
@Component({
    selector: 'app-plugin-review-dialog',
    imports: [AppSvgIconComponent, LoadingSpinnerComponent, PluginReviewPanelComponent],
    templateUrl: './plugin-review-dialog.component.html',
    styleUrl: './plugin-review-dialog.component.scss',
})
export class PluginReviewDialogComponent implements OnInit {
    protected readonly review = signal<PackageReview | null>(null);
    protected readonly busy = signal(false);
    protected readonly error = signal<PluginErrorView | null>(null);

    protected readonly titleId = PLUGIN_REVIEW_DIALOG_TITLE_ID;

    private readonly data = inject<PluginReviewDialogData>(DIALOG_DATA);
    private readonly dialogRef = inject<DialogRef<PluginReviewDialogResult>>(DialogRef);
    private readonly storage = inject(PluginsAdminStorageService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        if ('review' in this.data) {
            this.review.set(this.data.review);
            return;
        }
        this.storage
            .getPackageReview(this.data.packageId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (review) => this.review.set(review),
                error: (error: unknown) => this.error.set(toPluginErrorView(error, "Couldn't load the review.")),
            });
    }

    protected close(): void {
        this.dialogRef.close();
    }

    protected approve(review: PackageReview, request: PluginApproveRequest): void {
        this.busy.set(true);
        this.error.set(null);
        this.storage
            .approvePackage(review.id, request.untrustedAcknowledged)
            .pipe(
                finalize(() => this.busy.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (plugin) => {
                    this.toast.success(`${plugin.name} ${review.version} is approved.`);
                    this.dialogRef.close({ kind: 'approved', plugin });
                },
                error: (error: unknown) => this.error.set(toPluginErrorView(error, "Couldn't approve the package.")),
            });
    }

    protected reject(review: PackageReview): void {
        this.busy.set(true);
        this.error.set(null);
        this.storage
            .rejectPackage(review.id)
            .pipe(
                finalize(() => this.busy.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(`${review.name} ${review.version} was rejected and deleted.`);
                    this.dialogRef.close({ kind: 'rejected' });
                },
                error: (error: unknown) => this.error.set(toPluginErrorView(error, "Couldn't reject the package.")),
            });
    }
}

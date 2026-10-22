import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, LoadingSpinnerComponent } from '@shared/components';
import { finalize } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PackageReview, PluginApproveRequest, PluginDetail } from '../../models/plugin-admin.model';
import { PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginReviewPanelComponent } from '../plugin-review-panel/plugin-review-panel.component';

/** The review to show, or the package whose review to load. */
export type PluginReviewDialogData = { review: PackageReview } | { packageId: number };

export type PluginReviewDialogResult = { kind: 'approved'; plugin: PluginDetail } | { kind: 'rejected' };

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_REVIEW_DIALOG_TITLE_ID = 'plugin-review-dialog-title';

/**
 * A package's review with Approve and Reject: after an upload, for a plugin still waiting for approval, or for a new
 * version of an installed plugin ("Upgrade to <version>"). An approval refused because the review is outdated (the
 * installed version or the open upgrade changed meanwhile) loads the review again, so every box is ticked anew.
 */
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
        this.loadReview(this.data.packageId);
    }

    protected close(): void {
        this.dialogRef.close();
    }

    protected approve(review: PackageReview, request: PluginApproveRequest): void {
        this.busy.set(true);
        this.error.set(null);
        this.storage
            .approvePackage(review.id, request)
            .pipe(
                finalize(() => this.busy.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (plugin) => {
                    this.toast.success(approvedText(review, plugin));
                    this.dialogRef.close({ kind: 'approved', plugin });
                },
                error: (error: unknown) => {
                    const view = toPluginErrorView(error, "Couldn't approve the package.");
                    this.error.set(view);
                    if (view.code === 'review_outdated') this.loadReview(review.id);
                },
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

    /** A failed load keeps a review already shown, so the error above it says why it may be outdated. */
    private loadReview(packageId: number): void {
        this.storage
            .getPackageReview(packageId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (review) => this.review.set(review),
                error: (error: unknown) => this.error.set(toPluginErrorView(error, "Couldn't load the review.")),
            });
    }
}

/** "Weather 0.7.0 is approved."; for a new version, whether the upgrade is under way or already done. */
function approvedText(review: PackageReview, plugin: PluginDetail): string {
    if (!review.upgrade) return `${plugin.name} ${review.version} is approved.`;
    return plugin.open_upgrade
        ? `Upgrading ${plugin.name} to ${review.version}.`
        : `${plugin.name} is upgraded to ${review.version}.`;
}

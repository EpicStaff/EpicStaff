import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    Inject,
    inject,
    QueryList,
    signal,
    ViewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ConfirmationDialogService } from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { finalize } from 'rxjs/operators';

import { EntityTypeResult, ImportResult } from '../../../../core/models/import-result.model';
import { ImportReviewDialogCloseResult, ImportReviewDialogData } from '../../../../core/models/review-item.model';
import { ToastService } from '../../../../services/notifications/toast.service';
import { EntityGroupComponent } from './components/entity-group/entity-group.component';
import { ImportSummaryTabsComponent } from './components/import-summary-tabs/import-summary-tabs.component';
import { ReviewNavigatorComponent } from './components/review-navigator/review-navigator.component';
import { FLOW_NODE_TYPE_LABELS } from './constants/import-review.constants';
import { ReviewSessionStore } from './review-session.store';
import { getEntityTypeResult, getTotalItemsCount, getVisibleEntityTypes } from './utils/entity-result.util';

@Component({
    selector: 'app-import-review-dialog',
    imports: [ButtonComponent, ImportSummaryTabsComponent, EntityGroupComponent, ReviewNavigatorComponent],
    templateUrl: './import-review-dialog.component.html',
    styleUrls: ['./import-review-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [ReviewSessionStore],
})
export class ImportReviewDialogComponent {
    protected readonly store = inject(ReviewSessionStore);
    private readonly toastService = inject(ToastService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);

    @ViewChildren('entityGroup', { read: ElementRef })
    private entityGroupRefs!: QueryList<ElementRef<HTMLElement>>;

    public readonly importResult: ImportResult;
    public readonly visibleEntityTypes: string[];
    public readonly totalItemsCount: number;
    public readonly isSingleGroup: boolean;
    public readonly nodeTypeLabels = FLOW_NODE_TYPE_LABELS;

    public readonly highlightedGroup = signal<string | null>(null);
    private highlightTimeout: ReturnType<typeof setTimeout> | null = null;

    public readonly isImporting = signal(false);

    constructor(
        public dialogRef: DialogRef<ImportReviewDialogCloseResult>,
        @Inject(DIALOG_DATA) public data: ImportReviewDialogData
    ) {
        this.importResult = data.importResult;
        this.visibleEntityTypes = getVisibleEntityTypes(this.importResult);
        this.totalItemsCount = getTotalItemsCount(this.importResult);
        this.isSingleGroup = this.visibleEntityTypes.length <= 1;
        this.store.init(data.reviewItems ?? [], data.allFlowNodes ?? {});
    }

    public getEntityTypeResult(entityType: string): EntityTypeResult {
        return getEntityTypeResult(this.importResult, entityType) as EntityTypeResult;
    }

    public onTabClick(entityType: string): void {
        const index = this.visibleEntityTypes.indexOf(entityType);
        if (index === -1) return;

        const groupEl = this.entityGroupRefs?.toArray()[index]?.nativeElement;
        if (!groupEl) return;

        groupEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        this.triggerHighlight(entityType);
    }

    private triggerHighlight(entityType: string): void {
        if (this.highlightTimeout) clearTimeout(this.highlightTimeout);
        this.highlightedGroup.set(entityType);
        this.highlightTimeout = setTimeout(() => this.highlightedGroup.set(null), 1500);
    }

    public onCancel(): void {
        this.dialogRef.close({ action: 'cancel' });
    }

    public onImport(): void {
        if (this.isImporting()) return;

        if (!this.store.isReviewComplete()) {
            const unreviewed = this.store.unreviewedEntriesCount();
            const total = this.store.reviewableEntries.length;
            const isSingular = unreviewed === 1;

            this.confirmationDialogService
                .confirm(
                    {
                        title: 'Import without reviewing all code?',
                        message: `${unreviewed} of ${total} code block${total === 1 ? '' : 's'} ${
                            isSingular ? "hasn't" : "haven't"
                        } been opened yet.`,
                        cautionTitle: 'Attention',
                        caution: 'After import, this code runs in your workspace.',
                        confirmText: 'Import',
                        cancelText: 'Continue review',
                        type: 'warning',
                    },
                    { width: '485px' }
                )
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((result) => {
                    if (result === true) this.performImport();
                });
            return;
        }

        this.performImport();
    }

    private performImport(): void {
        this.isImporting.set(true);
        this.dialogRef.disableClose = true;
        this.data
            .importFn()
            .pipe(
                finalize(() => {
                    this.isImporting.set(false);
                    this.dialogRef.disableClose = false;
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (result) => this.dialogRef.close({ action: 'imported', result }),
                error: (error: HttpErrorResponse) => {
                    this.toastService.error(
                        extractHttpErrorMessage(error, 'Failed to import. Please check the file and try again.')
                    );
                },
            });
    }
}

import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    ConfirmationDialogService,
    DeleteButtonComponent,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import {
    escapeHtml,
    extractHttpErrorMessage,
    getRelativeTime,
    movedToRecycleBinMessage,
    pluralize,
    recycleBinNotice,
} from '@shared/utils';
import { catchError, finalize, forkJoin, map, Observable, of } from 'rxjs';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { AddSecretDialogComponent } from '../add-secret-dialog/add-secret-dialog.component';
import { SecretUsageDialogComponent } from '../secret-usage-dialog/secret-usage-dialog.component';

type UsedByFilter = 'unused' | 'deactivated' | null;

/** How one delete of a bulk delete ended: a 404 means another tab or user deleted the secret first. */
type BulkDeleteOutcome =
    | { name: string; result: 'deleted' | 'alreadyGone' }
    | { name: string; result: 'failed'; error: HttpErrorResponse };

// Must match .secrets-section-used-by-panel .selector__dropdown's width in the stylesheet.
const USED_BY_PANEL_WIDTH = 216;

const USED_BY_FILTER_ITEMS: SelectItem[] = [
    { name: 'All', value: null },
    { name: 'Deactivate', value: 'deactivated' },
    { name: 'Unused', value: 'unused' },
];

const GENERIC_FAILURE_REASON = 'Something went wrong.';

/** What happens to the resources that use a deleted secret: their link is kept while it's in the bin. */
const KEPT_LINKS_NOTE =
    "They stop working while it's in the recycle bin, and work again if you restore it. " +
    'Deleting it for good clears it from them.';

@Component({
    selector: 'app-secrets-section',
    templateUrl: './secrets-section.component.html',
    styleUrls: ['./secrets-section.component.scss'],
    imports: [
        SearchComponent,
        ButtonComponent,
        AppTableComponent,
        AppTableCellDirective,
        AppSvgIconComponent,
        DeleteButtonComponent,
        SelectComponent,
        LoadingSpinnerComponent,
        MatTooltip,
        HasPermissionDirective,
        FetchErrorStateComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SecretsSectionComponent implements OnInit {
    private readonly dialog = inject(Dialog);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly permissionsService = inject(PermissionsService);
    private readonly recycleBinSettings = inject(RecycleBinSettingsService);
    private readonly usedByFilterSelect = viewChild.required<SelectComponent>('usedByFilterSelect');

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
    public readonly canReadSecrets = computed(() => this.permissionsService.can(ResourceCode.Secrets, ActionCode.Read));
    public readonly canDeleteSecrets = computed(() =>
        this.permissionsService.can(ResourceCode.Secrets, ActionCode.Delete)
    );

    public readonly searchTerm = signal<string>('');
    public readonly usedByFilterItems = USED_BY_FILTER_ITEMS;
    public readonly usedByFilter = signal<UsedByFilter>(null);
    public readonly selectedRows = signal<TableRow[]>([]);
    /** True while a bulk delete's requests are in flight: a second click must not send them again. */
    protected readonly isBulkDeleting = signal(false);
    protected readonly bulkDeleteLabel = computed(() => `Delete selected (${this.selectedRows().length})`);

    public readonly status = signal<LoadingState>(LoadingState.IDLE);

    public readonly hasSecrets = computed(() => this.secretsStorageService.secrets().length > 0);

    // The search box and "USED BY" filter both narrow `secrets()` before app-table ever sees it,
    // so its own hasAnyFilter() (built-in column filters only) doesn't know about them. Without
    // reporting this, an external filter matching zero rows makes app-table treat it as "no data
    // has ever existed" and drop the header along with the body — see hasExternalFilter's doc.
    public readonly hasActiveExternalFilter = computed(
        () => this.searchTerm().trim().length > 0 || this.usedByFilter() !== null
    );

    public readonly secrets = computed<TableRow[]>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        const usedByFilter = this.usedByFilter();

        let secrets = this.secretsStorageService.secrets();
        if (term) {
            secrets = secrets.filter((secret) => secret.name.toLowerCase().includes(term));
        }
        if (usedByFilter === 'deactivated') {
            // No "deactivated" concept exists on the Secret model yet — always empty until it does.
            secrets = [];
        } else if (usedByFilter === 'unused') {
            secrets = secrets.filter((secret) => secret.usage_count.readable === 0 && secret.usage_count.hidden === 0);
        }

        return secrets.map(
            (secret): TableRow => ({
                id: secret.id,
                name: secret.name,
                preview: this.secretsStorageService.maskTail(secret.tail),
                usedByReadable: secret.usage_count.readable,
                usedByReadableLabel: pluralize(secret.usage_count.readable, 'resource', 'resources'),
                usedByHidden: secret.usage_count.hidden,
                updatedLabel: getRelativeTime(new Date(secret.updated_at)),
            })
        );
    });

    public readonly columns = computed<AppTableColumnDef[]>(() => [
        { key: 'name', label: 'NAME', width: '1fr' },
        { key: 'preview', label: 'PREVIEW', width: '128px' },
        {
            key: 'usedBy',
            label: 'USED BY',
            width: '128px',
            headerIcon: 'menu',
            headerIconActive: this.usedByFilter() !== null || this.usedByFilterSelect().open(),
            headerBadgeCount: this.usedByFilter() !== null ? this.secrets().length : 0,
        },
        { key: 'updated', label: 'UPDATED', width: '128px' },
        ...(this.canDeleteSecrets()
            ? [{ key: 'actions', label: 'ACTIONS', width: '96px', align: 'end' as const }]
            : []),
    ]);

    ngOnInit(): void {
        if (!this.canReadSecrets()) return;
        // Force a refresh on every mount — usage_count/usages can change from a flow or tool
        // editor visited between mounts, and the cached secrets list has no other invalidation
        // hook to know that happened.
        this.loadSecrets(true);
    }

    public refreshData(): void {
        this.status.set(LoadingState.LOADING);
        this.loadSecrets(true);
    }

    private loadSecrets(forceRefresh = false): void {
        this.status.set(LoadingState.LOADING);
        this.secretsStorageService
            .getSecrets(forceRefresh)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.status.set(LoadingState.LOADED),
                error: () => this.status.set(LoadingState.ERROR),
            });
    }

    public onAddSecret(): void {
        this.dialog.open(AddSecretDialogComponent, {
            width: '480px',
        });
    }

    public onSelectionChange(rows: TableRow[]): void {
        this.selectedRows.set(rows);
    }

    public onDeleteSecret(row: TableRow): void {
        const name = row['name'] as string;
        const caution = this.deleteUsageCaution(row['usedByReadable'], row['usedByHidden']);

        this.confirmationDialogService
            .confirm({
                title: 'Delete Secret',
                message: `You're about to delete <strong>${escapeHtml(name)}</strong>. ${recycleBinNotice(this.recycleBinSettings.retentionDays())}`,
                caution,
                cautionTitle: caution ? 'Caution' : undefined,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) return;

                this.secretsStorageService
                    .deleteSecret(row['id'] as number)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => {
                            this.toastService.success(movedToRecycleBinMessage(1, 'secret', 'secrets'));
                        },
                        error: (err: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(err)),
                    });
            });
    }

    public onBulkDelete(): void {
        const rows = this.selectedRows();
        if (!rows.length || this.isBulkDeleting()) return;

        const referencedCount = rows.filter((row) => this.usedByDisplay(row) !== 'unused').length;

        this.confirmationDialogService
            .confirm({
                title: 'Delete Secrets',
                message: `You're about to delete <strong>${pluralize(rows.length, 'secret', 'secrets')}</strong>. ${recycleBinNotice(this.recycleBinSettings.retentionDays(), rows.length)}`,
                caution: referencedCount
                    ? `<strong>${referencedCount}</strong> of the selected secrets are still referenced by other resources. ${KEPT_LINKS_NOTE}`
                    : undefined,
                cautionTitle: referencedCount ? 'Caution' : undefined,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) return;

                this.isBulkDeleting.set(true);
                forkJoin(rows.map((row) => this.deleteOneOfBulk(row)))
                    .pipe(
                        takeUntilDestroyed(this.destroyRef),
                        finalize(() => this.isBulkDeleting.set(false))
                    )
                    .subscribe((outcomes) => {
                        this.showBulkDeleteResult(outcomes);
                        // app-table keeps its own selection; it resets only because the reload swaps the table for the spinner.
                        this.selectedRows.set([]);
                        this.loadSecrets(true);
                    });
            });
    }

    public onHeaderIconClick(event: { key: string; target: HTMLElement }): void {
        if (event.key !== 'usedBy') return;
        this.usedByFilterSelect().openAt(event.target, USED_BY_PANEL_WIDTH);
    }

    public onUsedByFilterChange(value: unknown): void {
        this.usedByFilter.set(value as UsedByFilter);
    }

    // 'unknown' covers a row whose usage counts aren't valid numbers (e.g. usage_count is still
    // the old plain-number shape) — treated like 'hidden' rather than 'unused' so a caller never
    // reads a secret as safe to delete just because its usage couldn't be determined.
    public usedByDisplay(row: TableRow): 'clickable' | 'hidden' | 'unknown' | 'unused' {
        const readable = row['usedByReadable'];
        const hidden = row['usedByHidden'];
        if (typeof readable !== 'number' || typeof hidden !== 'number') return 'unknown';
        if (readable > 0) return 'clickable';
        if (hidden > 0) return 'hidden';
        return 'unused';
    }

    public onOpenUsage(row: TableRow): void {
        this.dialog.open(SecretUsageDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { secretId: row['id'] as number, secretName: row['name'] as string },
        });
    }

    private deleteUsageCaution(readable: unknown, hidden: unknown): string | undefined {
        if (typeof readable !== 'number' || typeof hidden !== 'number') {
            return "This secret's usage couldn't be determined. Deleting it may still break something that depends on it.";
        }
        if (readable === 0 && hidden === 0) return undefined;

        const parts: string[] = [];
        if (readable > 0) parts.push(`<strong>${pluralize(readable, 'resource', 'resources')}</strong> you can see`);
        if (hidden > 0) parts.push(`<strong>some resources</strong> you don't have permission to view`);

        return `This secret is still referenced by ${parts.join(' and ')}. ${KEPT_LINKS_NOTE}`;
    }

    /** Settles on its own, so one failed delete never cancels the others. */
    private deleteOneOfBulk(row: TableRow): Observable<BulkDeleteOutcome> {
        const name = row['name'] as string;
        return this.secretsStorageService.deleteSecret(row['id'] as number).pipe(
            map((): BulkDeleteOutcome => ({ name, result: 'deleted' })),
            catchError((error: HttpErrorResponse) =>
                of<BulkDeleteOutcome>(
                    error.status === 404 ? { name, result: 'alreadyGone' } : { name, result: 'failed', error }
                )
            )
        );
    }

    private showBulkDeleteResult(outcomes: BulkDeleteOutcome[]): void {
        const deletedCount = outcomes.filter((outcome) => outcome.result === 'deleted').length;
        const alreadyGone = outcomes.filter((outcome) => outcome.result === 'alreadyGone');
        const failed = outcomes.filter(
            (outcome): outcome is Extract<BulkDeleteOutcome, { result: 'failed' }> => outcome.result === 'failed'
        );

        const alreadyGoneNote = alreadyGone.length
            ? `${alreadyGone.length} ${alreadyGone.length === 1 ? 'was' : 'were'} already deleted: ${this.joinNames(alreadyGone)}.`
            : '';
        if (deletedCount > 0) {
            const moved = movedToRecycleBinMessage(deletedCount, 'secret', 'secrets');
            this.toastService.success(alreadyGoneNote ? `${moved} ${alreadyGoneNote}` : moved);
        } else if (alreadyGoneNote) {
            this.toastService.info(alreadyGoneNote);
        }

        if (failed.length) {
            this.toastService.error(
                `Couldn't delete ${pluralize(failed.length, 'secret', 'secrets')}. ${this.failureReason(failed)} Not deleted: ${this.joinNames(failed)}.`
            );
        }
    }

    /** The server's reason when every failure gives the same one; different reasons have no single one to show. */
    private failureReason(failed: Extract<BulkDeleteOutcome, { result: 'failed' }>[]): string {
        const reasons = failed.map((outcome) => extractHttpErrorMessage(outcome.error, GENERIC_FAILURE_REASON).trim());
        if (reasons.some((reason) => reason !== reasons[0])) return GENERIC_FAILURE_REASON;
        return /[.!?]$/.test(reasons[0]) ? reasons[0] : `${reasons[0]}.`;
    }

    private joinNames(outcomes: BulkDeleteOutcome[]): string {
        return outcomes.map((outcome) => outcome.name).join(', ');
    }
}

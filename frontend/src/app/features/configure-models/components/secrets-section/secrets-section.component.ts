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
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage, getRelativeTime } from '@shared/utils';
import { forkJoin } from 'rxjs';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { ToastService } from '../../../../services/notifications';
import { getSecretUsage, getSecretUsageCount } from '../../models/secret-usage.model';
import { SETTINGS_DIALOG_SIZE } from '../../services/configure-models-dialog.service';
import { AddSecretDialogComponent } from '../add-secret-dialog/add-secret-dialog.component';
import { SecretUsageDialogComponent } from '../secret-usage-dialog/secret-usage-dialog.component';

type UsedByFilter = 'unused' | 'deactivated' | null;

const USED_BY_FILTER_ITEMS: SelectItem[] = [
    { name: 'All', value: null },
    { name: 'Deactivate', value: 'deactivated' },
    { name: 'Unused', value: 'unused' },
];

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
        SelectComponent,
        LoadingSpinnerComponent,
        MatTooltip,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SecretsSectionComponent implements OnInit {
    private readonly dialog = inject(Dialog);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly usedByFilterSelect = viewChild.required<SelectComponent>('usedByFilterSelect');

    public readonly searchTerm = signal<string>('');
    public readonly usedByFilterItems = USED_BY_FILTER_ITEMS;
    public readonly usedByFilter = signal<UsedByFilter>(null);
    public readonly selectedRows = signal<TableRow[]>([]);

    public readonly status = signal<LoadingState>(LoadingState.IDLE);
    public readonly errorMessage = signal<string | null>(null);

    public readonly hasSecrets = computed(() => this.secretsStorageService.secrets().length > 0);

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
            secrets = secrets.filter((secret) => getSecretUsageCount(secret.id) === 0);
        }

        return secrets.map(
            (secret): TableRow => ({
                id: secret.id,
                name: secret.name,
                preview: this.secretsStorageService.maskTail(secret.tail),
                usedByCount: getSecretUsageCount(secret.id),
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
        { key: 'actions', label: 'ACTIONS', width: '96px' },
    ]);

    ngOnInit(): void {
        this.loadSecrets();
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
                error: () => {
                    this.errorMessage.set('Failed to load secrets. Please try again.');
                    this.status.set(LoadingState.ERROR);
                },
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
        const usedByCount = row['usedByCount'] as number;

        this.confirmationDialogService
            .confirm({
                title: 'Delete Secret',
                message: `You're about to delete <strong>${name}</strong>. This action can't be undone.`,
                caution: usedByCount
                    ? `This secret is still referenced by <strong>${usedByCount} resources</strong>. They'll fall back to their <strong>NULL</strong> value once it's removed.`
                    : undefined,
                cautionTitle: usedByCount ? 'Caution' : undefined,
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
                        next: () => this.toastService.success('Secret deleted'),
                        error: (err: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(err)),
                    });
            });
    }

    public onBulkDelete(): void {
        const rows = this.selectedRows();
        if (!rows.length) return;

        const referencedCount = rows.filter((row) => (row['usedByCount'] as number) > 0).length;

        this.confirmationDialogService
            .confirm({
                title: 'Delete Secrets',
                message: `You're about to delete <strong>${rows.length} secret${rows.length === 1 ? '' : 's'}</strong>. This action can't be undone.`,
                caution: referencedCount
                    ? `<strong>${referencedCount}</strong> of the selected secrets are still referenced by other resources. They'll fall back to their <strong>NULL</strong> value once removed.`
                    : undefined,
                cautionTitle: referencedCount ? 'Caution' : undefined,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) return;

                const ids = rows.map((row) => row['id'] as number);
                forkJoin(ids.map((id) => this.secretsStorageService.deleteSecret(id)))
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => {
                            this.toastService.success(`${ids.length} secret${ids.length === 1 ? '' : 's'} deleted`);
                            this.selectedRows.set([]);
                        },
                        error: (err: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(err)),
                    });
            });
    }

    public onHeaderIconClick(event: { key: string; target: HTMLElement }): void {
        if (event.key !== 'usedBy') return;
        this.usedByFilterSelect().openAt(event.target, 216);
    }

    public onUsedByFilterChange(value: unknown): void {
        this.usedByFilter.set(value as UsedByFilter);
    }

    public onOpenUsage(row: TableRow): void {
        const id = row['id'] as number;
        const name = row['name'] as string;

        this.dialog.open(SecretUsageDialogComponent, {
            ...SETTINGS_DIALOG_SIZE,
            data: { secretName: name, usage: getSecretUsage(id) },
        });
    }
}

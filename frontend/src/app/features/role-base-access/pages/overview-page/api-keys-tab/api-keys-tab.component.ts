import { CdkConnectedOverlay, CdkOverlayOrigin } from '@angular/cdk/overlay';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    AppTableRowAction,
    ConfirmationDialogService,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { ApiKeyStatus, GetApiKeyWithOwnerResponse } from '@shared/models';
import { getRelativeTime } from '@shared/utils';
import { combineLatest, debounceTime, distinctUntilChanged, EMPTY, forkJoin, map, of, switchMap } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../services/notifications';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';
import { UserAvatarComponent } from '../../../components/user-avatar/user-avatar.component';
import { AdminApiKeysService } from '../../../services/admin/api-keys.service';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import {
    API_KEY_STATUS_ORDER,
    apiKeyExpiresLabel,
    apiKeyExpiryUrgency,
    apiKeyStatusIcon,
    apiKeyStatusLabel,
    getAdminDeleteConfirmationData,
    getAdminRevokeConfirmationData,
    getBulkDeleteConfirmationData,
    getBulkRevokeConfirmationData,
} from '../../../utils';

const STATUS_ITEMS: SelectItem[] = [
    { name: 'All', value: null },
    { name: 'Active', value: ApiKeyStatus.ACTIVE, icon: apiKeyStatusIcon(ApiKeyStatus.ACTIVE) ?? undefined },
    { name: 'Expired', value: ApiKeyStatus.EXPIRED, icon: apiKeyStatusIcon(ApiKeyStatus.EXPIRED) ?? undefined },
    { name: 'Revoked', value: ApiKeyStatus.REVOKED, icon: apiKeyStatusIcon(ApiKeyStatus.REVOKED) ?? undefined },
];

@Component({
    selector: 'app-api-keys-tab',
    templateUrl: './api-keys-tab.component.html',
    styleUrls: ['./api-keys-tab.component.scss'],
    imports: [
        AppTableComponent,
        AppTableCellDirective,
        AppSvgIconComponent,
        CdkConnectedOverlay,
        CdkOverlayOrigin,
        LoadingSpinnerComponent,
        SearchComponent,
        StatusBadgeComponent,
        UserAvatarComponent,
        DatePipe,
        SelectComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApiKeysTabComponent {
    private readonly apiKeysService = inject(AdminApiKeysService);
    private readonly permissionService = inject(PermissionsService);
    private readonly organizationsService = inject(OrganizationsStorageService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    protected readonly totalApiKeysCount = signal<number | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly isBulkLoading = signal(false);
    protected readonly isBulkMenuOpen = signal(false);
    protected readonly selectedItems = signal<TableRow[]>([]);
    protected readonly keys = signal<GetApiKeyWithOwnerResponse[]>([]);
    protected readonly orgFilterValue = signal<number | null>(null);

    protected readonly searchTerm = signal('');
    protected readonly ownerFilterId = signal<number | null>(null);
    protected readonly statusFilter = signal<ApiKeyStatus | null>(null);

    private readonly refreshTrigger = signal(0);

    private readonly knownOwners = signal<Map<number, { name: string; email: string }>>(new Map());

    protected readonly ownerFilterItems = computed<SelectItem[]>(() => {
        const items: SelectItem[] = [...this.knownOwners().entries()]
            .sort(([, a], [, b]) => a.name.localeCompare(b.name))
            .map(([id, o]) => ({ name: o.name, subtitle: o.email, value: id }));
        return [{ name: 'All', value: null }, ...items];
    });

    private readonly rowActions: AppTableRowAction[] = [
        {
            icon: 'x',
            tooltip: 'Revoke key',
            variant: 'warning',
            hidden: (row) => row['status'] !== ApiKeyStatus.ACTIVE,
            onClick: (row) => this.onRevokeKey(row),
        },
        {
            icon: 'trash',
            tooltip: 'Delete key',
            variant: (row) => (row['status'] === ApiKeyStatus.ACTIVE ? 'danger' : 'default'),
            onClick: (row) => this.onDeleteKey(row),
        },
    ];

    protected readonly orgsSelectItems = computed<SelectItem[]>(() => {
        const items: SelectItem[] = this.organizationsService.organizations().map((o) => ({
            name: o.name,
            value: o.id,
        }));

        return [{ name: 'All Organizations', value: null }, ...items];
    });

    protected readonly columns = computed<AppTableColumnDef[]>(() => [
        {
            key: 'owner',
            label: 'OWNER',
            width: 'minmax(180px, 1.5fr)',
            filterItems: this.ownerFilterItems(),
            filterKind: 'single',
            filterSearchable: true,
            filterServerSide: true,
        },
        { key: 'name', label: 'NAME', width: 'minmax(140px, 1.5fr)' },
        { key: 'key', label: 'KEY', width: 'minmax(140px, 1.2fr)' },
        { key: 'created', label: 'CREATED', width: 'minmax(110px, 1fr)' },
        { key: 'expires', label: 'EXPIRES', width: 'minmax(100px, 1fr)' },
        { key: 'lastUsed', label: 'LAST USED', width: 'minmax(100px, 1fr)' },
        {
            key: 'status',
            label: 'STATUS',
            width: 'minmax(120px, 1fr)',
            filterItems: STATUS_ITEMS,
            filterKind: 'single',
            filterServerSide: true,
            align: 'center',
        },
        { key: 'actions', label: 'ACTIONS', width: '110px', align: 'center', actions: this.rowActions },
    ]);

    protected readonly tableData = computed<TableRow[]>(() =>
        this.keys()
            .map((k) => ({
                id: k.id,
                name: k.name,
                key: k.prefix + '...',
                created: k.created_at,
                expiresAt: k.expires_at,
                expiresLabel: apiKeyExpiresLabel(k),
                expiryUrgency: apiKeyExpiryUrgency(k),
                lastUsedLabel: getRelativeTime(k.last_used_at),
                status: k.status,
                ownerId: k.owner.id,
                ownerName: k.owner.display_name || k.owner.email,
                ownerEmail: k.owner.email,
            }))
            .sort((a, b) => API_KEY_STATUS_ORDER.get(a.status)! - API_KEY_STATUS_ORDER.get(b.status)!)
    );

    private readonly filters$ = combineLatest([
        toObservable(this.ownerFilterId),
        toObservable(this.statusFilter),
        toObservable(this.orgFilterValue),
        toObservable(this.searchTerm).pipe(debounceTime(300), distinctUntilChanged()),
        toObservable(this.refreshTrigger),
    ]);

    constructor() {
        if (this.canFilterByOrg) {
            this.organizationsService.getOrganizations().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        }
        this.filters$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    this.isLoading.set(true);
                    const orgId = this.canFilterByOrg ? this.orgFilterValue() : undefined;
                    return this.apiKeysService
                        .getApiKeys(
                            {
                                user: this.ownerFilterId() ?? undefined,
                                status: this.statusFilter() ?? undefined,
                                search: this.searchTerm() || undefined,
                            },
                            orgId
                        )
                        .pipe(
                            finalize(() => this.isLoading.set(false)),
                            catchError((err) => {
                                this.toast.error(err.error?.message ?? 'Failed to reload API keys');
                                return EMPTY;
                            })
                        );
                })
            )
            .subscribe((keys) => {
                if (this.totalApiKeysCount() === null) this.totalApiKeysCount.set(keys.length);
                this.keys.set(keys);
                this.rememberOwners(keys);
            });
    }

    onOrgFilterChange(value: unknown): void {
        this.orgFilterValue.set(value === null || value === undefined ? null : Number(value));
        this.totalApiKeysCount.set(null);
    }

    onFilterChange({ key, values }: { key: string; values: unknown[] }): void {
        const first = values[0] ?? null;
        if (key === 'owner') {
            this.ownerFilterId.set(first === null ? null : Number(first));
        } else if (key === 'status') {
            this.statusFilter.set(first === null ? null : (first as ApiKeyStatus));
        }
    }

    onSelectionChange(selected: TableRow[]): void {
        this.selectedItems.set(selected);
    }

    toggleBulkMenu(): void {
        this.isBulkMenuOpen.update((v) => !v);
    }

    closeBulkMenu(): void {
        this.isBulkMenuOpen.set(false);
    }

    onBulkRevoke(): void {
        this.closeBulkMenu();
        const isSomeRevoked = this.selectedItems().some((r) => r['status'] === ApiKeyStatus.REVOKED);
        const activeRows = this.selectedItems().filter((r) => r['status'] === ApiKeyStatus.ACTIVE);
        const count = activeRows.length;
        if (!count) {
            if (isSomeRevoked) this.toast.info('All selected keys are already revoked');
            return;
        }

        const items = activeRows.map((r) => ({ name: r['name'] as string, status: r['status'] as ApiKeyStatus }));
        this.confirmation
            .confirm(getBulkRevokeConfirmationData(items))
            .pipe(
                switchMap((confirmed) => {
                    if (confirmed !== true) return EMPTY;
                    this.isBulkLoading.set(true);
                    return forkJoin(
                        activeRows.map((r) =>
                            this.apiKeysService.revokeApiKey(r['id'] as number).pipe(
                                map(() => true),
                                catchError(() => of(false))
                            )
                        )
                    );
                }),
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isBulkLoading.set(false))
            )
            .subscribe((results) => {
                const failed = results.filter((ok) => !ok).length;
                const succeeded = count - failed;
                if (isSomeRevoked) this.toast.info('Some selected keys were already revoked');
                if (succeeded > 0) this.toast.success(`${succeeded} ${succeeded === 1 ? 'key' : 'keys'} revoked`);
                if (failed > 0) this.toast.error(`${failed} ${failed === 1 ? 'key' : 'keys'} failed to revoke`);
                this.loadApiKeys();
            });
    }

    onBulkDelete(): void {
        this.closeBulkMenu();
        const rows = this.selectedItems();
        if (!rows.length) return;
        const count = rows.length;
        const items = rows.map((r) => ({ name: r['name'] as string, status: r['status'] as ApiKeyStatus }));

        this.confirmation
            .confirm(getBulkDeleteConfirmationData(items))
            .pipe(
                switchMap((confirmed) => {
                    if (confirmed !== true) return EMPTY;
                    this.isBulkLoading.set(true);
                    return forkJoin(
                        rows.map((r) =>
                            this.apiKeysService.deleteApiKey(r['id'] as number).pipe(
                                map(() => true),
                                catchError(() => of(false))
                            )
                        )
                    );
                }),
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isBulkLoading.set(false))
            )
            .subscribe((results) => {
                const failed = results.filter((ok) => !ok).length;
                const succeeded = count - failed;
                if (succeeded > 0) this.toast.success(`${succeeded} ${succeeded === 1 ? 'key' : 'keys'} deleted`);
                if (failed > 0) this.toast.error(`${failed} ${failed === 1 ? 'key' : 'keys'} failed to delete`);
                this.loadApiKeys();
            });
    }

    onRevokeKey(row: TableRow): void {
        const id = row['id'] as number;
        this.confirmation
            .confirm(getAdminRevokeConfirmationData(row['name'] as string))
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.apiKeysService.revokeApiKey(id) : EMPTY)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(`"${row['name']}" was revoked`);
                    this.loadApiKeys();
                },
                error: (err) => this.toast.error(err.error?.message ?? 'Failed to revoke API key'),
            });
    }

    onDeleteKey(row: TableRow): void {
        const id = row['id'] as number;
        this.confirmation
            .confirm(getAdminDeleteConfirmationData(row['ownerName'] as string))
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.apiKeysService.deleteApiKey(id) : EMPTY)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(`"${row['name']}" was deleted`);
                    this.loadApiKeys();
                },
                error: (err) => this.toast.error(err.error?.message ?? 'Failed to delete API key'),
            });
    }

    /** Triggers a re-fetch by incrementing `refreshTrigger`, which causes the `switchMap` pipeline
     *  to emit and automatically cancels any prior in-flight request. */
    private loadApiKeys(): void {
        this.refreshTrigger.update((v) => v + 1);
    }

    /** Merges any newly-seen owners into the cache used by the owner filter dropdown. */
    private rememberOwners(keys: GetApiKeyWithOwnerResponse[]): void {
        this.knownOwners.update((cache) => {
            const next = new Map(cache);
            for (const k of keys) {
                next.set(k.owner.id, {
                    name: k.owner.display_name || k.owner.email,
                    email: k.owner.email,
                });
            }
            return next;
        });
    }

    protected readonly canFilterByOrg = this.permissionService.isSuperadmin;
    protected readonly ApiKeyStatus = ApiKeyStatus;
    protected readonly statusLabel = apiKeyStatusLabel;
    protected readonly statusIcon = apiKeyStatusIcon;
}

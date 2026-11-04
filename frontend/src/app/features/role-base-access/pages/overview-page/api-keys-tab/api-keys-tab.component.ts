import { CdkTrapFocus } from '@angular/cdk/a11y';
import { CdkConnectedOverlay, CdkOverlayOrigin } from '@angular/cdk/overlay';
import { DatePipe } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ConfirmationDialogService,
    DeleteButtonComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    StopButtonComponent,
    TableColumnPickerComponent,
    TableRow,
    UserAvatarComponent,
} from '@shared/components';
import { ActionCode, ApiKeyStatus, GetApiKeyWithOwnerResponse, ResourceCode } from '@shared/models';
import { getRelativeTime } from '@shared/utils';
import { combineLatest, debounceTime, distinctUntilChanged, EMPTY, forkJoin, map, of, switchMap } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { ActiveOrgService } from '../../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../services/notifications';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';
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
    rbacErrorMessage,
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
        TableColumnPickerComponent,
        AppSvgIconComponent,
        CdkConnectedOverlay,
        CdkOverlayOrigin,
        LoadingSpinnerComponent,
        SearchComponent,
        StatusBadgeComponent,
        UserAvatarComponent,
        DatePipe,
        DeleteButtonComponent,
        StopButtonComponent,
        CdkTrapFocus,
        MatTooltip,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApiKeysTabComponent {
    // Takes the focus back when a menu action or a row action removes the control that had it.
    private readonly bulkButton = viewChild.required<ElementRef<HTMLButtonElement>>('bulkButton');

    private readonly apiKeysService = inject(AdminApiKeysService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly organizationsService = inject(OrganizationsStorageService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    protected readonly totalApiKeysCount = signal(0);
    protected readonly isLoading = signal(true);
    protected readonly isBulkLoading = signal(false);
    protected readonly isBulkMenuOpen = signal(false);
    /** Only ids are kept: the selected rows are read from the latest list, so a reload never leaves a stale status behind. */
    private readonly selectedIds = signal<ReadonlySet<number>>(new Set());
    protected readonly keys = signal<GetApiKeyWithOwnerResponse[]>([]);

    protected readonly searchTerm = signal('');
    protected readonly ownerFilterId = signal<number | null>(null);
    protected readonly statusFilter = signal<ApiKeyStatus | null>(null);
    protected readonly orgFilterIds = signal<number[]>([]);

    private readonly refreshTrigger = signal(0);

    private readonly knownOwners = signal<Map<number, { name: string; email: string }>>(new Map());

    protected readonly readableOrgs = computed<{ id: number; name: string }[]>(() => {
        if (this.permissionsService.isSuperadmin) {
            return this.organizationsService
                .organizations()
                .filter((o) => o.is_active)
                .map((o) => ({ id: o.id, name: o.name }));
        }
        return this.permissionsService.orgsWith(ResourceCode.ApiKeys, ActionCode.Read);
    });

    protected readonly orgFilterItems = computed<SelectItem[]>(() =>
        this.readableOrgs().map((o) => ({ name: o.name, value: o.id }))
    );

    /** Preselected org filter — follows the active org, but only if the caller can read API keys there.
     *  Otherwise stays empty so the load falls back to all readable orgs. */
    private readonly activeOrgDefault = computed<number[] | undefined>(() => {
        const id = this.activeOrgService.activeOrgId();
        if (id === null) return undefined;
        if (this.permissionsService.isSuperadmin) return [id];
        return this.readableOrgs().some((o) => o.id === id) ? [id] : undefined;
    });

    protected readonly ownerFilterItems = computed<SelectItem[]>(() => {
        const items: SelectItem[] = [...this.knownOwners().entries()]
            .sort(([, a], [, b]) => a.name.localeCompare(b.name))
            .map(([id, o]) => ({ name: o.name, subtitle: o.email, value: id }));
        return [{ name: 'All', value: null }, ...items];
    });

    protected readonly columns = computed<AppTableColumnDef[]>(() => [
        {
            key: 'owner',
            label: 'Owner',
            width: '220px',
            pinned: 'start',
            filterItems: this.ownerFilterItems(),
            filterKind: 'single',
            filterSearchable: true,
            filterServerSide: true,
        },
        { key: 'name', label: 'Name', width: 'minmax(140px, 1.5fr)' },
        {
            key: 'orgName',
            label: 'Organization',
            width: 'minmax(140px, 1.5fr)',
            filterItems: this.orgFilterItems(),
            filterKind: 'multi',
            filterSearchable: true,
            filterServerSide: true,
            defaultValues: this.activeOrgDefault(),
        },
        { key: 'key', label: 'Key', width: 'minmax(140px, 1.2fr)' },
        { key: 'created', label: 'Created', width: 'minmax(110px, 1fr)' },
        { key: 'expires', label: 'Expires', width: 'minmax(100px, 1fr)' },
        { key: 'lastUsed', label: 'Last Used', width: 'minmax(100px, 1fr)' },
        {
            key: 'status',
            label: 'Status',
            width: 'minmax(120px, 1fr)',
            filterItems: STATUS_ITEMS,
            filterKind: 'single',
            filterServerSide: true,
        },
        { key: 'actions', label: 'Actions', width: '110px', align: 'end', pinned: 'end' },
    ]);

    /** Revoke is offered only for active keys the caller can retire. */
    canRevokeRow(row: TableRow): boolean {
        return row['status'] === ApiKeyStatus.ACTIVE && this.canRetireRow(row);
    }

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
                ownerAvatar: k.owner.avatar_url,
                ownerName: k.owner.display_name || k.owner.email,
                ownerEmail: k.owner.email,
                orgId: k.org_id,
                orgName: k.org_name,
            }))
            .sort((a, b) => API_KEY_STATUS_ORDER.get(a.status)! - API_KEY_STATUS_ORDER.get(b.status)!)
    );

    protected readonly selectedItems = computed<TableRow[]>(() => {
        const selectedIds = this.selectedIds();
        return this.tableData().filter((row) => selectedIds.has(row['id'] as number));
    });
    protected readonly isBulkDisabled = computed(() => this.selectedItems().length === 0 || this.isBulkLoading());

    protected readonly isRowSelectable = (row: TableRow): boolean => this.canRetireRow(row);

    private readonly filters$ = combineLatest([
        toObservable(this.ownerFilterId),
        toObservable(this.statusFilter),
        toObservable(this.orgFilterIds),
        toObservable(this.searchTerm).pipe(debounceTime(300), distinctUntilChanged()),
        toObservable(this.refreshTrigger),
    ]);

    constructor() {
        this.ensureOrgsLoaded();

        this.filters$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    this.isLoading.set(true);
                    return this.apiKeysService
                        .getApiKeys({
                            user: this.ownerFilterId() ?? undefined,
                            status: this.statusFilter() ?? undefined,
                            search: this.searchTerm() || undefined,
                            orgIds: this.orgFilterIds().length ? this.orgFilterIds() : undefined,
                        })
                        .pipe(
                            finalize(() => this.isLoading.set(false)),
                            catchError((err) => {
                                this.toast.error(rbacErrorMessage(err, 'Failed to load API keys'));
                                return EMPTY;
                            })
                        );
                })
            )
            .subscribe((envelope) => {
                this.totalApiKeysCount.set(envelope.count);
                this.keys.set(envelope.results);
                this.rememberOwners(envelope.results);
            });
    }

    private ensureOrgsLoaded(): void {
        if (!this.permissionsService.isSuperadmin) return;
        if (this.organizationsService.isOrganizationsLoaded()) return;
        this.organizationsService.getOrganizations().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    canRetireRow(row: TableRow): boolean {
        return this.permissionsService.canInOrg(row['orgId'] as number, ResourceCode.ApiKeys, ActionCode.Delete);
    }

    onFilterChange({ key, values }: { key: string; values: unknown[] }): void {
        const first = values[0] ?? null;
        if (key === 'orgName') {
            this.orgFilterIds.set(values.map((v) => Number(v)).filter((n) => Number.isFinite(n)));
        } else if (key === 'owner') {
            this.ownerFilterId.set(first === null ? null : Number(first));
        } else if (key === 'status') {
            this.statusFilter.set(first === null ? null : (first as ApiKeyStatus));
        }
    }

    onSelectionChange(selected: TableRow[]): void {
        this.selectedIds.set(new Set(selected.map((row) => row['id'] as number)));
    }

    toggleBulkMenu(): void {
        if (this.isBulkDisabled()) return;
        this.isBulkMenuOpen.update((v) => !v);
    }

    closeBulkMenu(): void {
        this.isBulkMenuOpen.set(false);
    }

    onBulkRevoke(): void {
        this.closeMenuBeforeDialog();
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
                this.reload();
            });
    }

    onBulkDelete(): void {
        this.closeMenuBeforeDialog();
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
                this.reload();
            });
    }

    onRevokeKey(row: TableRow): void {
        const id = row['id'] as number;
        this.confirmation
            .confirm(getAdminRevokeConfirmationData(row['name'] as string))
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.apiKeysService.revokeApiKey(id) : EMPTY)),
                finalize(() => this.reload()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(`"${row['name']}" was revoked`);
                    this.bulkButton().nativeElement.focus();
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
                finalize(() => this.reload()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(`"${row['name']}" was deleted`);
                    this.bulkButton().nativeElement.focus();
                },
                error: (err) => this.toast.error(err.error?.message ?? 'Failed to delete API key'),
            });
    }

    // The confirmation dialog hands the focus back to what had it on open: the trigger, not the menu item going away.
    private closeMenuBeforeDialog(): void {
        this.bulkButton().nativeElement.focus();
        this.closeBulkMenu();
    }

    /** Triggers a re-fetch by bumping `refreshTrigger`; `switchMap` cancels any in-flight request. */
    private reload(): void {
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

    protected readonly ApiKeyStatus = ApiKeyStatus;
    protected readonly statusLabel = apiKeyStatusLabel;
    protected readonly statusIcon = apiKeyStatusIcon;
}

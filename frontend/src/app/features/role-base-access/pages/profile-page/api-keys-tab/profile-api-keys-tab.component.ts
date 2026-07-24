import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    AppTableRowAction,
    ButtonComponent,
    ConfirmationDialogService,
    TableRow,
} from '@shared/components';
import { GetMyApiKeyResponse } from '@shared/models';
import { daysUntil, getRelativeTime } from '@shared/utils';
import { EMPTY, switchMap } from 'rxjs';

import { ProfileService } from '../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../services/notifications';
import { CreateApiKeyDialogComponent } from '../../../components/create-api-key-dialog/create-api-key-dialog.component';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';

@Component({
    selector: 'app-profile-api-keys-tab',
    templateUrl: './profile-api-keys-tab.component.html',
    styleUrls: ['./profile-api-keys-tab.component.scss'],
    imports: [
        AppTableComponent,
        AppTableCellDirective,
        ButtonComponent,
        DatePipe,
        MatTooltip,
        StatusBadgeComponent,
        AppSvgIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileApiKeysTabComponent implements OnInit {
    private currentUserService = inject(ProfileService);
    private destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);
    private toast = inject(ToastService);
    private confirmation = inject(ConfirmationDialogService);

    protected readonly MAX_PERSONAL_KEYS = 5;

    private readonly rowActions: AppTableRowAction[] = [
        {
            icon: 'x',
            tooltip: 'Revoke key',
            variant: 'warning',
            hidden: (row) => row['status'] !== 'active',
            onClick: (row) => this.onRevokeKey(row),
        },
        {
            icon: 'trash',
            tooltip: 'Delete key',
            variant: (row) => (row['status'] === 'active' ? 'danger' : 'default'),
            onClick: (row) => this.onDeleteKey(row),
        },
    ];

    protected readonly columns: AppTableColumnDef[] = [
        { key: 'name', label: 'NAME', width: 'minmax(140px, 2fr)' },
        { key: 'key', label: 'KEY', width: 'minmax(120px, 1.2fr)' },
        { key: 'created', label: 'CREATED', width: 'minmax(110px, 1fr)' },
        { key: 'expires', label: 'EXPIRES', width: 'minmax(100px, 1fr)' },
        { key: 'lastUsed', label: 'LAST USED', width: 'minmax(100px, 1fr)' },
        { key: 'status', label: 'STATUS', width: '110px', align: 'center' },
        { key: 'actions', label: 'ACTIONS', width: '110px', align: 'center', actions: this.rowActions },
    ];

    private readonly keys = signal<GetMyApiKeyResponse[]>([]);

    protected readonly activeCount = computed(() => this.keys().filter((k) => k.status === 'active').length);

    protected readonly tableData = computed<TableRow[]>(() => {
        const items = this.keys().map((k) => ({
            id: k.id,
            name: k.name,
            key: k.prefix + '...',
            created: k.created_at,
            expiresAt: k.expires_at,
            expiresLabel: this.expiresLabel(k),
            expiryUrgency: this.keyExpiryUrgency(k),
            lastUsedLabel: getRelativeTime(k.last_used_at),
            status: k.status,
        }));

        const statusOrder = new Map([
            ['active', 0],
            ['expired', 1],
            ['revoked', 2],
        ]);

        return items.sort((a, b) => statusOrder.get(a.status)! - statusOrder.get(b.status)!);
    });

    protected readonly maxCountReached = computed(() => this.activeCount() >= this.MAX_PERSONAL_KEYS);

    ngOnInit() {
        this.fetchApiKeys();
    }

    onCreateKey(): void {
        const dialogRef = this.dialog.open(CreateApiKeyDialogComponent, {
            width: '560px',
        });

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) this.fetchApiKeys();
        });
    }

    statusLabel(status: string): string {
        const labels: Record<string, string> = { active: 'Active', expired: 'Expired', revoked: 'Revoked' };
        return labels[status] ?? status;
    }

    statusIcon(status: string): string | null {
        const icons: Record<string, string> = { expired: 'expired', revoked: 'x' };
        return icons[status] ?? null;
    }

    onRevokeKey(row: TableRow): void {
        const id = row['id'] as number;
        const name = row['name'] as string;
        this.confirmation
            .confirm({
                title: 'Revoke this API key?',
                message: `The "${name}" API key will be revoked immediately and can no longer be used to authenticate.`,
                caution: 'Any client or integration currently using this key will lose access.',
                type: 'danger',
                confirmText: 'Revoke',
                cancelText: 'Cancel',
            })
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.currentUserService.revokeApiKey(id) : EMPTY)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(`"${name}" was revoked`);
                    this.fetchApiKeys();
                },
                error: (err) => this.toast.error(err.error?.message ?? 'Failed to revoke API key'),
            });
    }

    onDeleteKey(row: TableRow): void {
        const id = row['id'] as number;
        const name = row['name'] as string;
        const isActive = row['status'] === 'active';
        this.confirmation
            .confirm({
                title: 'Delete this API key?',
                message: `The "${name}" API key will be permanently deleted. This action cannot be undone.`,
                caution: isActive
                    ? 'This key is still active — any client currently using it will lose access.'
                    : undefined,
                type: isActive ? 'danger' : 'info',
                confirmText: 'Delete',
                cancelText: 'Cancel',
            })
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.currentUserService.deleteApiKey(id) : EMPTY)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(`"${name}" was deleted`);
                    this.fetchApiKeys();
                },
                error: (err) => this.toast.error(err.error?.message ?? 'Failed to delete API key'),
            });
    }

    private fetchApiKeys(): void {
        this.currentUserService
            .getMyApiKeys()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (keys) => this.keys.set(keys),
                error: (err) => this.toast.error(err.error.message),
            });
    }

    private expiresLabel(key: GetMyApiKeyResponse): string {
        if (key.status === 'expired') return 'Expired';
        if (!key.expires_at) return 'Never';
        const days = daysUntil(key.expires_at);
        if (days <= 0) return 'Expired';
        return `in ${days} ${days === 1 ? 'day' : 'days'}`;
    }

    private keyExpiryUrgency(key: GetMyApiKeyResponse) {
        if (key.status !== 'active' || !key.expires_at) return 'default';
        return this.expiryUrgency(daysUntil(key.expires_at));
    }

    private expiryUrgency(daysLeft: number | null): 'default' | 'orange' | 'red' {
        if (daysLeft === null || daysLeft <= 0) return 'default';
        if (daysLeft <= 3) return 'red';
        if (daysLeft <= 7) return 'orange';
        return 'default';
    }
}

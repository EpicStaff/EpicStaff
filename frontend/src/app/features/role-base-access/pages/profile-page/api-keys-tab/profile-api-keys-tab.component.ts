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
import { ApiKeyStatus, GetMyApiKeyResponse } from '@shared/models';
import { getRelativeTime } from '@shared/utils';
import { EMPTY, switchMap } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { ProfileService } from '../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../services/notifications';
import { CreateApiKeyDialogComponent } from '../../../components/create-api-key-dialog/create-api-key-dialog.component';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';
import {
    API_KEY_STATUS_ORDER,
    apiKeyExpiresLabel,
    apiKeyExpiryUrgency,
    apiKeyStatusIcon,
    apiKeyStatusLabel,
    getProfileDeleteConfirmationData,
    getProfileRevokeConfirmationData,
} from '../../../utils';

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

    protected readonly activeCount = computed(() => this.keys().filter((k) => k.status === ApiKeyStatus.ACTIVE).length);

    protected readonly tableData = computed<TableRow[]>(() => {
        const items = this.keys().map((k) => ({
            id: k.id,
            name: k.name,
            key: k.prefix + '...',
            created: k.created_at,
            expiresAt: k.expires_at,
            expiresLabel: apiKeyExpiresLabel(k),
            expiryUrgency: apiKeyExpiryUrgency(k),
            lastUsedLabel: getRelativeTime(k.last_used_at),
            status: k.status,
        }));

        return items.sort((a, b) => API_KEY_STATUS_ORDER.get(a.status)! - API_KEY_STATUS_ORDER.get(b.status)!);
    });

    protected readonly maxCountReached = computed(() => this.activeCount() >= this.MAX_PERSONAL_KEYS);

    ngOnInit() {
        this.fetchApiKeys();
    }

    onCreateKey(): void {
        const dialogRef = this.dialog.open(CreateApiKeyDialogComponent, {
            width: '560px',
        });

        dialogRef.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.fetchApiKeys())
            )
            .subscribe();
    }

    onRevokeKey(row: TableRow): void {
        const id = row['id'] as number;
        const name = row['name'] as string;
        this.confirmation
            .confirm(getProfileRevokeConfirmationData(name))
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.currentUserService.revokeApiKey(id) : EMPTY)),
                finalize(() => this.fetchApiKeys()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => this.toast.success(`"${name}" was revoked`),
                error: (err) => this.toast.error(err.error?.message ?? 'Failed to revoke API key'),
            });
    }

    onDeleteKey(row: TableRow): void {
        const id = row['id'] as number;
        const name = row['name'] as string;
        const isActive = row['status'] === ApiKeyStatus.ACTIVE;
        this.confirmation
            .confirm(getProfileDeleteConfirmationData(name, isActive))
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.currentUserService.deleteApiKey(id) : EMPTY)),
                finalize(() => this.fetchApiKeys()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => this.toast.success(`"${name}" was deleted`),
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

    protected readonly ApiKeyStatus = ApiKeyStatus;
    protected readonly statusLabel = apiKeyStatusLabel;
    protected readonly statusIcon = apiKeyStatusIcon;
}

import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { GetOrganizationResponse } from '@shared/models';
import { finalize } from 'rxjs';

import { AdminOrganizationsService } from '../../../role-base-access/services/admin/organizations.service';
import { PluginGrant } from '../../models/plugin-admin.model';
import { PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { fetchAllOrganizations } from '../../utils/plugin-organizations.util';

export interface PluginGrantDialogData {
    identifier: string;
    name: string;
}

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_GRANT_DIALOG_TITLE_ID = 'plugin-grant-dialog-title';

/** Grants a plugin to one active organization, picked from the SuperAdmin's organization list. */
@Component({
    selector: 'app-plugin-grant-dialog',
    imports: [MatTooltip, AppSvgIconComponent, ButtonComponent, SelectComponent],
    templateUrl: './plugin-grant-dialog.component.html',
    styleUrl: './plugin-grant-dialog.component.scss',
})
export class PluginGrantDialogComponent implements OnInit {
    protected readonly organizations = signal<GetOrganizationResponse[]>([]);
    protected readonly isLoading = signal(true);
    protected readonly isGranting = signal(false);
    protected readonly organizationId = signal<number | null>(null);
    protected readonly error = signal<PluginErrorView | null>(null);
    protected readonly organizationItems = computed<SelectItem[]>(() =>
        this.organizations().map((organization) => ({ name: organization.name, value: organization.id }))
    );
    protected readonly canGrant = computed(() => this.organizationId() !== null && !this.isGranting());

    protected readonly data = inject<PluginGrantDialogData>(DIALOG_DATA);
    protected readonly titleId = PLUGIN_GRANT_DIALOG_TITLE_ID;

    private readonly dialogRef = inject<DialogRef<PluginGrant>>(DialogRef);
    private readonly organizationsApi = inject(AdminOrganizationsService);
    private readonly storage = inject(PluginsAdminStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        fetchAllOrganizations(this.organizationsApi, { is_active: [true] })
            .pipe(
                finalize(() => this.isLoading.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (organizations) => this.organizations.set(organizations),
                error: (error: unknown) => this.error.set(toPluginErrorView(error, "Couldn't load the organizations.")),
            });
    }

    protected onOrganizationChange(value: unknown): void {
        this.organizationId.set(typeof value === 'number' ? value : null);
        this.error.set(null);
    }

    protected grant(): void {
        const organizationId = this.organizationId();
        if (organizationId === null || this.isGranting()) return;
        this.isGranting.set(true);
        this.error.set(null);
        this.storage
            .createGrant(this.data.identifier, organizationId)
            .pipe(
                finalize(() => this.isGranting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (grant) => this.dialogRef.close(grant),
                error: (error: unknown) => this.error.set(toPluginErrorView(error, "Couldn't grant the plugin.")),
            });
    }

    protected close(): void {
        this.dialogRef.close();
    }
}

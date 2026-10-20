import { DatePipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    LoadingSpinnerComponent,
    PaginationControlsComponent,
    TableRow,
} from '@shared/components';
import { catchError, finalize, of, switchMap, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginGrant } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { PLUGIN_GRANT_STATE_LABELS, PluginBadgeTone, pluginGrantStateTone } from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';

export const PLUGIN_GRANTS_PAGE_SIZE = 20;

const COLUMNS: AppTableColumnDef[] = [
    { key: 'organization', label: 'Organization', width: 'minmax(180px, 2fr)' },
    { key: 'state', label: 'State', width: 'minmax(120px, 1fr)' },
    { key: 'grantedBy', label: 'Granted by', width: 'minmax(180px, 2fr)' },
    { key: 'grantedAt', label: 'Granted', width: 'minmax(140px, 1fr)' },
];

/** The organizations a plugin is granted to, a page at a time, and the Grant action. */
@Component({
    selector: 'app-plugin-grants-table',
    imports: [
        AppTableCellDirective,
        AppTableComponent,
        ButtonComponent,
        DatePipe,
        LoadingSpinnerComponent,
        PaginationControlsComponent,
        PluginBadgeComponent,
    ],
    templateUrl: './plugin-grants-table.component.html',
    styleUrl: './plugin-grants-table.component.scss',
})
export class PluginGrantsTableComponent {
    readonly identifier = input.required<string>();
    readonly pluginName = input.required<string>();
    /** Only a running plugin can be granted. */
    readonly canGrant = input(false);

    protected readonly page = signal(1);
    protected readonly grants = signal<PluginGrant[]>([]);
    protected readonly count = signal(0);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly rows = computed<TableRow[]>(() => this.grants().map((grant) => ({ id: grant.id })));
    private readonly grantsById = computed(() => new Map(this.grants().map((grant) => [grant.id, grant])));
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({
        identifier: this.identifier(),
        page: this.page(),
        reload: this.reloads(),
    }));

    protected readonly columns = COLUMNS;
    protected readonly pageSize = PLUGIN_GRANTS_PAGE_SIZE;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly dialogs = inject(PluginDialogsService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier, page }) =>
                    this.storage.listGrants(identifier, page, PLUGIN_GRANTS_PAGE_SIZE).pipe(
                        catchError((error: unknown) => {
                            this.loadError.set(toPluginErrorView(error, "Couldn't load the grants.").message);
                            return of(null);
                        }),
                        finalize(() => this.isLoading.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((response) => {
                if (!response) return;
                this.grants.set(response.results);
                this.count.set(response.count);
            });
    }

    protected grantOf(row: TableRow): PluginGrant | undefined {
        return this.grantsById().get(row['id'] as number);
    }

    protected stateLabel(grant: PluginGrant): string {
        return PLUGIN_GRANT_STATE_LABELS[grant.state];
    }

    protected stateTone(grant: PluginGrant): PluginBadgeTone {
        return pluginGrantStateTone(grant.state);
    }

    protected onPageChange(page: number): void {
        this.page.set(page);
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    protected openGrant(): void {
        this.dialogs
            .openGrant({ identifier: this.identifier(), name: this.pluginName() })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((grant) => {
                if (!grant) return;
                this.toast.success(`${this.pluginName()} is granted to ${grant.organization.name}.`);
                this.reload();
            });
    }
}

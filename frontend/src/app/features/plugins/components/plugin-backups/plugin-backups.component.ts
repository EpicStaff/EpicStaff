import { DatePipe } from '@angular/common';
import {
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { ButtonComponent, LoadingSpinnerComponent } from '@shared/components';
import { formatFileSize } from '@shared/utils';
import { catchError, filter, finalize, of, switchMap, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginBackup, PluginBackupList, PluginRestore } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { PLUGIN_BACKUP_NOT_RESTORABLE_LABELS, pluginBackupTitle } from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

/** A backup as its row shows it. */
interface BackupRow {
    backup: PluginBackup;
    title: string;
    /** "holds 0.6.0 · 7.3 MB". */
    facts: string;
    /** "Not restorable: from an earlier upgrade"; `null` for a restorable backup. */
    notRestorable: string | null;
}

/**
 * The backups the plugin node holds of a plugin's database, newest first: why each was taken, the version whose
 * database it holds, its size and time, and Restore… for those the server says are restorable (else why not). The list
 * is loaded again whenever `refreshKey` changes (on every runtime poll, and when the open upgrade moves) and after a
 * restore was asked for.
 *
 * A failed load shows an alert with Retry. A poll that fails again leaves that alert as it is, so it is not announced
 * anew every few seconds and Retry keeps its focus; it goes once a list arrives, or at once on Retry.
 */
@Component({
    selector: 'app-plugin-backups',
    imports: [ButtonComponent, DatePipe, LoadingSpinnerComponent],
    templateUrl: './plugin-backups.component.html',
    styleUrl: './plugin-backups.component.scss',
})
export class PluginBackupsComponent {
    readonly identifier = input.required<string>();
    readonly pluginName = input.required<string>();
    readonly databaseName = input.required<string>();
    /** Changes whenever what the backups allow may have changed: the open upgrade's stage, failure or restore. */
    readonly refreshKey = input('');
    /** Bumped each time "Restore backup…" is chosen: bring the list into view; `0` until then. */
    readonly revealed = input(0);
    /** A restore was asked for; the plugin's open upgrade now carries it. */
    readonly restoreRequested = output<PluginRestore>();

    private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

    protected readonly list = signal<PluginBackupList | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly rows = computed<BackupRow[]>(() => (this.list()?.backups ?? []).map((backup) => toRow(backup)));
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({
        identifier: this.identifier(),
        refreshKey: this.refreshKey(),
        reload: this.reloads(),
    }));

    private readonly revealEffect = effect(() => {
        const heading = this.heading()?.nativeElement;
        if (!heading || this.revealed() === 0) return;
        untracked(() => {
            heading.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
            heading.focus({ preventScroll: true });
        });
    });

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly dialogs = inject(PluginDialogsService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    if (this.list() === null && this.loadError() === null) this.isLoading.set(true);
                }),
                switchMap(({ identifier }) =>
                    this.storage.listBackups(identifier).pipe(
                        catchError((error: unknown) => {
                            this.loadError.set(toPluginErrorView(error, "Couldn't load the backups.").message);
                            return of(null);
                        }),
                        finalize(() => this.isLoading.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((list) => {
                if (!list) return;
                this.list.set(list);
                this.loadError.set(null);
            });
    }

    /** Retry: the alert and its button go, so the heading takes the focus. */
    protected retry(): void {
        this.heading()?.nativeElement.focus({ preventScroll: true });
        this.reload();
    }

    protected openRestore(row: BackupRow): void {
        const list = this.list();
        if (!list || !row.backup.restorable) return;
        this.dialogs
            .openRestore({
                identifier: this.identifier(),
                pluginName: this.pluginName(),
                databaseName: this.databaseName(),
                backup: row.backup,
                verificationPhrase: list.verification_phrase,
            })
            .pipe(
                filter((restore): restore is PluginRestore => restore !== undefined),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((restore) => {
                this.toast.success(`Restoring ${this.databaseName()} from the backup "${row.title}".`);
                this.restoreRequested.emit(restore);
                this.reload();
            });
    }

    /** A load someone asked for starts without the last failure's alert. */
    private reload(): void {
        this.loadError.set(null);
        this.reloads.update((count) => count + 1);
    }
}

function toRow(backup: PluginBackup): BackupRow {
    const reason = backup.not_restorable_reason;
    return {
        backup,
        title: pluginBackupTitle(backup),
        facts: `holds ${backup.version} · ${formatFileSize(backup.size_bytes, 'auto')}`,
        notRestorable:
            backup.restorable || reason === null
                ? null
                : `Not restorable: ${PLUGIN_BACKUP_NOT_RESTORABLE_LABELS[reason]}`,
    };
}

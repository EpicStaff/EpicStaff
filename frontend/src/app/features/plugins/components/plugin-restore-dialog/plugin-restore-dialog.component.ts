import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { formatDate } from '@angular/common';
import { Component, computed, DestroyRef, inject, LOCALE_ID, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { filter, finalize } from 'rxjs';

import { PluginBackup, PluginRestore } from '../../models/plugin-admin.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { pluginBackupTitle } from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

/** The backup to restore, and what the dialog names. */
export interface PluginRestoreDialogData {
    identifier: string;
    pluginName: string;
    /** The plugin's database, as the runtime names it. */
    databaseName: string;
    backup: PluginBackup;
    /** `restore-<identifier>`, as the backup list sends it. */
    verificationPhrase: string;
}

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_RESTORE_DIALOG_TITLE_ID = 'plugin-restore-dialog-title';

/**
 * Restores a backup of a plugin's database during an upgrade that failed: says what it replaces and that a backup of
 * the current database comes first, and asks for the phrase the server sent. Restore is enabled only when the phrase is
 * typed exactly (nothing is trimmed, case counts); it is sent as typed and checked again by the server. A refusal
 * keeps the dialog open with the reason; success closes it with the restore under way. A click outside does not close
 * it; Escape, Cancel and the close button do, except while the request is under way.
 */
@Component({
    selector: 'app-plugin-restore-dialog',
    imports: [MatTooltip, AppSvgIconComponent, ButtonComponent, ReactiveFormsModule],
    templateUrl: './plugin-restore-dialog.component.html',
    styleUrl: './plugin-restore-dialog.component.scss',
})
export class PluginRestoreDialogComponent {
    protected readonly isRestoring = signal(false);
    protected readonly restoreError = signal<string | null>(null);
    protected readonly canRestore = computed(
        () => this.typedPhrase() === this.data.verificationPhrase && !this.isRestoring()
    );

    protected readonly data = inject<PluginRestoreDialogData>(DIALOG_DATA);
    protected readonly titleId = PLUGIN_RESTORE_DIALOG_TITLE_ID;
    protected readonly backupTitle = pluginBackupTitle(this.data.backup);
    protected readonly phraseControl = new FormControl('', { nonNullable: true });
    protected readonly question: string;

    private readonly dialogRef = inject<DialogRef<PluginRestore>>(DialogRef);
    private readonly storage = inject(PluginsAdminStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly typedPhrase = toSignal(this.phraseControl.valueChanges, { initialValue: '' });

    constructor() {
        const takenAt = formatDate(this.data.backup.created_at, 'medium', inject(LOCALE_ID));
        this.question =
            `Replace ${this.data.databaseName} with this backup from ${takenAt}? Changes since then are lost. ` +
            'A backup of the current database is taken first, so you can undo this.';
        this.dialogRef.keydownEvents
            .pipe(
                filter((event) => event.key === 'Escape'),
                takeUntilDestroyed()
            )
            .subscribe(() => this.close());
    }

    protected close(): void {
        if (!this.isRestoring()) this.dialogRef.close();
    }

    protected restore(): void {
        if (!this.canRestore()) return;
        this.isRestoring.set(true);
        this.restoreError.set(null);
        this.storage
            .restoreBackup(this.data.identifier, this.data.backup.id, this.typedPhrase())
            .pipe(
                finalize(() => this.isRestoring.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (restore) => this.dialogRef.close(restore),
                error: (error: unknown) =>
                    this.restoreError.set(toPluginErrorView(error, "Couldn't restore the backup.").message),
            });
    }
}

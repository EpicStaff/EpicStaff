import { Dialog } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import {
    PLUGIN_GRANT_DIALOG_TITLE_ID,
    PluginGrantDialogComponent,
    PluginGrantDialogData,
} from '../components/plugin-grant-dialog/plugin-grant-dialog.component';
import {
    PLUGIN_PURGE_DIALOG_TITLE_ID,
    PluginGrantPurgeTarget,
    PluginPurgeDialogComponent,
    PluginPurgeDialogData,
    PluginPurgeDialogResult,
    PluginPurgeTarget,
} from '../components/plugin-purge-dialog/plugin-purge-dialog.component';
import {
    PLUGIN_RESTORE_DIALOG_TITLE_ID,
    PluginRestoreDialogComponent,
    PluginRestoreDialogData,
} from '../components/plugin-restore-dialog/plugin-restore-dialog.component';
import {
    PLUGIN_REVIEW_DIALOG_TITLE_ID,
    PluginReviewDialogComponent,
    PluginReviewDialogData,
    PluginReviewDialogResult,
} from '../components/plugin-review-dialog/plugin-review-dialog.component';
import {
    PLUGIN_SUSPEND_DIALOG_TITLE_ID,
    PluginSuspendDialogComponent,
    PluginSuspendDialogData,
} from '../components/plugin-suspend-dialog/plugin-suspend-dialog.component';
import {
    PLUGIN_UNINSTALL_DIALOG_TITLE_ID,
    PluginUninstallDialogComponent,
    PluginUninstallDialogData,
} from '../components/plugin-uninstall-dialog/plugin-uninstall-dialog.component';
import {
    PLUGIN_UPLOAD_DIALOG_TITLE_ID,
    PluginUploadDialogComponent,
} from '../components/plugin-upload-dialog/plugin-upload-dialog.component';
import { PackageReview, PluginDetail, PluginGrant, PluginRestore } from '../models/plugin-admin.model';

/** Opens the SuperAdmin plugin dialogs; each observable emits the dialog's result, or `undefined` when dismissed. */
@Injectable({ providedIn: 'root' })
export class PluginDialogsService {
    private readonly dialog = inject(Dialog);

    openUpload(): Observable<PackageReview | undefined> {
        return this.dialog.open<PackageReview>(PluginUploadDialogComponent, {
            ariaLabelledBy: PLUGIN_UPLOAD_DIALOG_TITLE_ID,
            disableClose: true,
        }).closed;
    }

    openReview(data: PluginReviewDialogData): Observable<PluginReviewDialogResult | undefined> {
        return this.dialog.open<PluginReviewDialogResult, PluginReviewDialogData>(PluginReviewDialogComponent, {
            ariaLabelledBy: PLUGIN_REVIEW_DIALOG_TITLE_ID,
            disableClose: true,
            data,
        }).closed;
    }

    openGrant(data: PluginGrantDialogData): Observable<PluginGrant | undefined> {
        return this.dialog.open<PluginGrant, PluginGrantDialogData>(PluginGrantDialogComponent, {
            ariaLabelledBy: PLUGIN_GRANT_DIALOG_TITLE_ID,
            data,
        }).closed;
    }

    /** Emits the suspended grant; a stray click outside does not close it, Escape, Cancel and the close button do. */
    openSuspend(data: PluginSuspendDialogData): Observable<PluginGrant | undefined> {
        return this.dialog.open<PluginGrant, PluginSuspendDialogData>(PluginSuspendDialogComponent, {
            ariaLabelledBy: PLUGIN_SUSPEND_DIALOG_TITLE_ID,
            disableClose: true,
            data,
        }).closed;
    }

    /** Emits the uninstalled plugin; closes as the suspend dialog does. */
    openUninstall(data: PluginUninstallDialogData): Observable<PluginDetail | undefined> {
        return this.dialog.open<PluginDetail, PluginUninstallDialogData>(PluginUninstallDialogComponent, {
            ariaLabelledBy: PLUGIN_UNINSTALL_DIALOG_TITLE_ID,
            disableClose: true,
            data,
        }).closed;
    }

    /** Emits the grant whose data is being deleted; closes as the suspend dialog does. */
    openGrantPurge(data: PluginGrantPurgeTarget): Observable<PluginGrant | undefined> {
        return this.openPurge({ scope: 'grant', ...data }).pipe(
            map((result) => (result?.scope === 'grant' ? result.grant : undefined))
        );
    }

    /** Emits the plugin being deleted; closes as the suspend dialog does. */
    openPluginPurge(data: PluginPurgeTarget): Observable<PluginDetail | undefined> {
        return this.openPurge({ scope: 'plugin', ...data }).pipe(
            map((result) => (result?.scope === 'plugin' ? result.plugin : undefined))
        );
    }

    /** Emits the restore under way; closes as the suspend dialog does. */
    openRestore(data: PluginRestoreDialogData): Observable<PluginRestore | undefined> {
        return this.dialog.open<PluginRestore, PluginRestoreDialogData>(PluginRestoreDialogComponent, {
            ariaLabelledBy: PLUGIN_RESTORE_DIALOG_TITLE_ID,
            disableClose: true,
            data,
        }).closed;
    }

    private openPurge(data: PluginPurgeDialogData): Observable<PluginPurgeDialogResult | undefined> {
        return this.dialog.open<PluginPurgeDialogResult, PluginPurgeDialogData>(PluginPurgeDialogComponent, {
            ariaLabelledBy: PLUGIN_PURGE_DIALOG_TITLE_ID,
            disableClose: true,
            data,
        }).closed;
    }
}

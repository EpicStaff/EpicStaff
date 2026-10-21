import { Dialog } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
    PLUGIN_GRANT_DIALOG_TITLE_ID,
    PluginGrantDialogComponent,
    PluginGrantDialogData,
} from '../components/plugin-grant-dialog/plugin-grant-dialog.component';
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
    PLUGIN_UPLOAD_DIALOG_TITLE_ID,
    PluginUploadDialogComponent,
} from '../components/plugin-upload-dialog/plugin-upload-dialog.component';
import { PackageReview, PluginGrant } from '../models/plugin-admin.model';

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

    /** Emits the suspended grant; a stray click outside does not close it, Cancel and the close button do. */
    openSuspend(data: PluginSuspendDialogData): Observable<PluginGrant | undefined> {
        return this.dialog.open<PluginGrant, PluginSuspendDialogData>(PluginSuspendDialogComponent, {
            ariaLabelledBy: PLUGIN_SUSPEND_DIALOG_TITLE_ID,
            disableClose: true,
            data,
        }).closed;
    }
}

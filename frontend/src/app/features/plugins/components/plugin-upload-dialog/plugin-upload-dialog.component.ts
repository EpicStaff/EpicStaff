import { DialogRef } from '@angular/cdk/dialog';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, FileUploaderComponent } from '@shared/components';
import { formatFileSize } from '@shared/utils';
import { finalize, Subscription } from 'rxjs';

import { PackageReview } from '../../models/plugin-admin.model';
import { PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

/** The file extension of a plugin package. */
export const PLUGIN_PACKAGE_EXTENSION = '.esplugin';

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_UPLOAD_DIALOG_TITLE_ID = 'plugin-upload-dialog-title';

/**
 * Uploads one `.esplugin` package and closes with its review (the caller shows it). Closing while the upload runs
 * cancels it.
 */
@Component({
    selector: 'app-plugin-upload-dialog',
    imports: [AppSvgIconComponent, ButtonComponent, FileUploaderComponent],
    templateUrl: './plugin-upload-dialog.component.html',
    styleUrl: './plugin-upload-dialog.component.scss',
})
export class PluginUploadDialogComponent {
    protected readonly file = signal<File | null>(null);
    /** Percent sent, or `null` when the size is unknown or nothing is being sent. */
    protected readonly progress = signal<number | null>(null);
    protected readonly isUploading = signal(false);
    protected readonly error = signal<PluginErrorView | null>(null);
    protected readonly fileSize = computed(() => formatFileSize(this.file()?.size, 'auto'));
    protected readonly canUpload = computed(() => this.file() !== null && !this.isUploading());

    protected readonly acceptedExtension = PLUGIN_PACKAGE_EXTENSION;
    protected readonly titleId = PLUGIN_UPLOAD_DIALOG_TITLE_ID;

    private readonly dialogRef = inject<DialogRef<PackageReview>>(DialogRef);
    private readonly storage = inject(PluginsAdminStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private upload: Subscription | null = null;

    protected onFilesSelected(files: FileList): void {
        const file = files.item(0);
        if (!file || this.isUploading()) return;
        if (!file.name.toLowerCase().endsWith(PLUGIN_PACKAGE_EXTENSION)) {
            this.onFileRejected();
            return;
        }
        this.file.set(file);
        this.error.set(null);
    }

    protected onFileRejected(): void {
        this.error.set({ code: null, message: `Choose a ${PLUGIN_PACKAGE_EXTENSION} package.`, items: [] });
    }

    protected startUpload(): void {
        const file = this.file();
        if (!file || this.isUploading()) return;
        this.isUploading.set(true);
        this.progress.set(0);
        this.error.set(null);
        this.upload = this.storage
            .uploadPackage(file)
            .pipe(
                finalize(() => {
                    this.isUploading.set(false);
                    this.progress.set(null);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (event) => {
                    if (event.kind === 'progress') {
                        this.progress.set(event.total ? Math.round((event.loaded / event.total) * 100) : null);
                        return;
                    }
                    this.dialogRef.close(event.review);
                },
                error: (error: unknown) => this.error.set(toPluginErrorView(error, "Couldn't upload the package.")),
            });
    }

    protected close(): void {
        this.upload?.unsubscribe();
        this.dialogRef.close();
    }
}

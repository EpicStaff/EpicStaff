import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { take } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { FileUploaderComponent } from '../file-uploader/file-uploader.component';
import { ImageCropperDialogComponent } from './image-cropper-dialog/image-cropper-dialog.component';

@Component({
    selector: 'app-avatar-upload',
    templateUrl: './avatar-upload.component.html',
    styleUrls: ['./avatar-upload.component.scss'],
    imports: [FileUploaderComponent, AppSvgIconComponent, MatTooltipModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AvatarUploadComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);

    initialUrl = input<string | null>(null);

    selectedFile = signal<File | null>(null);
    previewUrl = signal<string | null>(null);
    existingCleared = signal(false);

    fileSizeLabel = computed(() => {
        const size = this.selectedFile()?.size ?? 0;
        if (size >= 1024 * 1024) {
            return `${(size / 1024 / 1024).toFixed(1)} MB`;
        }
        return `${Math.round(size / 1024)} KB`;
    });

    showExisting = computed(() => !!this.initialUrl() && !this.existingCleared() && !this.selectedFile());

    imageChange = output<File | null>();
    existingRemoved = output<void>();

    constructor() {
        this.destroyRef.onDestroy(() => this.revokePreviewUrl());
    }

    onFilesUploaded(files: FileList): void {
        const file = files[0];
        if (!file) return;

        this.dialog
            .open<File | null>(ImageCropperDialogComponent, { data: { file } })
            .closed.pipe(take(1))
            .subscribe((croppedFile) => {
                if (croppedFile) {
                    this.revokePreviewUrl();
                    this.selectedFile.set(croppedFile);
                    this.previewUrl.set(URL.createObjectURL(croppedFile));
                    this.imageChange.emit(croppedFile);
                }
            });
    }

    onFilesRejected(): void {
        this.toast.error('Unsupported file type. Please use JPG or PNG.');
    }

    onClear(): void {
        this.revokePreviewUrl();
        this.selectedFile.set(null);
        this.imageChange.emit(null);
    }

    onRemoveExisting(): void {
        this.existingCleared.set(true);
        this.existingRemoved.emit();
    }

    private revokePreviewUrl(): void {
        const url = this.previewUrl();
        if (url) {
            URL.revokeObjectURL(url);
            this.previewUrl.set(null);
        }
    }
}

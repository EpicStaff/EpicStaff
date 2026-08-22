import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { ImageCroppedEvent, ImageCropperComponent } from 'ngx-image-cropper';

@Component({
    selector: 'app-image-cropper-dialog',
    templateUrl: './image-cropper-dialog.component.html',
    styleUrls: ['./image-cropper-dialog.component.scss'],
    imports: [ImageCropperComponent, ButtonComponent, AppSvgIconComponent, MatTooltip],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ImageCropperDialogComponent {
    private dialogRef = inject(DialogRef<File | null>);
    readonly data = inject<{ file: File }>(DIALOG_DATA);

    readonly croppedBlob = signal<Blob | null>(null);

    onImageCropped(event: ImageCroppedEvent): void {
        this.croppedBlob.set(event.blob ?? null);
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }

    onConfirm(): void {
        const blob = this.croppedBlob();
        if (!blob) return;

        const file = new File([blob], this.data.file.name, { type: 'image/jpeg' });
        this.dialogRef.close(file);
    }
}

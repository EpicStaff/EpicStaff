import { ChangeDetectionStrategy, Component, output, signal } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-file-uploader',
    templateUrl: './file-uploader.component.html',
    styleUrls: ['./file-uploader.component.scss'],
    imports: [AppSvgIconComponent],

    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FileUploaderComponent {
    isDragging = signal<boolean>(false);

    filesUploaded = output<FileList>();

    onDragOver(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();
        this.isDragging.set(true);
    }

    onDragLeave(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();

        const target = event.currentTarget as HTMLElement;
        const rect = target.getBoundingClientRect();
        const { clientX, clientY } = event;

        if (clientX <= rect.left || clientX >= rect.right || clientY <= rect.top || clientY >= rect.bottom) {
            this.isDragging.set(false);
        }
    }

    onDrop(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();
        this.isDragging.set(false);

        if (event.dataTransfer?.files.length) {
            this.filesUploaded.emit(event.dataTransfer.files);
        }
    }

    onFileSelect(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files) {
            this.filesUploaded.emit(input.files);
            input.value = '';
        }
    }
}

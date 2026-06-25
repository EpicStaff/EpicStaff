import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';

import {
    SelectStorageFilesDialogComponent,
    SelectStorageFilesDialogData,
    SelectStorageFilesDialogResult,
} from '../../../features/files/components/select-storage-files-dialog/select-storage-files-dialog.component';
import { GraphFileRecord } from '../../../features/files/models/storage.models';
import { StorageApiService } from '../../../features/files/services/storage-api.service';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-flow-files-button',
    imports: [AppSvgIconComponent, MatTooltip],
    templateUrl: './flow-files-button.component.html',
    styleUrls: ['./flow-files-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowFilesButtonComponent implements OnInit {
    readonly flowId = input.required<number>();
    readonly flowName = input.required<string>();

    private storageApiService = inject(StorageApiService);
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);

    readonly attachedFiles = signal<GraphFileRecord[]>([]);
    readonly attachedCount = computed(() => this.attachedFiles().length);

    ngOnInit(): void {
        this.loadAttachedFiles();
    }

    openDialog(): void {
        const ref = this.dialog.open<SelectStorageFilesDialogResult, SelectStorageFilesDialogData>(
            SelectStorageFilesDialogComponent,
            {
                data: { flowId: this.flowId(), flowName: this.flowName() },
                panelClass: 'custom-dialog-panel',
            }
        );

        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result?.changed) {
                this.loadAttachedFiles();
            }
        });
    }

    private loadAttachedFiles(): void {
        this.storageApiService
            .getGraphFiles(this.flowId())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (files) => this.attachedFiles.set(files),
                error: () => this.attachedFiles.set([]),
            });
    }
}

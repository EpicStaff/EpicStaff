import { Component, ChangeDetectionStrategy, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DialogRef } from '@angular/cdk/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';

export interface ImportFlowOptions {
    preserveUuids: boolean;
}

@Component({
    selector: 'app-import-flow-options-dialog',
    imports: [CommonModule, ButtonComponent, AppIconComponent, MatTooltipModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './import-flow-options-dialog.html',
    styleUrl: 'import-flow-options-dialog.scss',
})
export class ImportFlowOptionsDialogComponent {
    public preserveUuids = signal(false);

    constructor(private dialogRef: DialogRef<ImportFlowOptions | undefined>) {}

    public confirm(): void {
        this.dialogRef.close({ preserveUuids: this.preserveUuids() });
    }

    public cancel(): void {
        this.dialogRef.close();
    }
}

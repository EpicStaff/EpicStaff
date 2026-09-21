import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { CopyFieldComponent } from '@shared/components';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

export interface CodeFileDetailsDialogData {
    entrypoint: string;
    libraries: string[];
}

@Component({
    selector: 'app-code-file-details-dialog',
    imports: [AppSvgIconComponent, MatTooltipModule, CopyFieldComponent],
    templateUrl: './code-file-details-dialog.component.html',
    styleUrls: ['./code-file-details-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CodeFileDetailsDialogComponent {
    readonly dialogRef = inject(DialogRef<void>);
    readonly data = inject<CodeFileDetailsDialogData>(DIALOG_DATA);

    get entrypointSignature(): string {
        return `def ${this.data.entrypoint}(...)`;
    }

    close(): void {
        this.dialogRef.close();
    }
}

import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, Inject } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { RestoreWarning } from '../../models/graph.model';

export interface RestoreWarningsDialogData {
    warnings: RestoreWarning[];
}

@Component({
    selector: 'app-restore-warnings-dialog',
    imports: [AppSvgIconComponent, ButtonComponent],
    templateUrl: './restore-warnings-dialog.component.html',
    styleUrl: './restore-warnings-dialog.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RestoreWarningsDialogComponent {
    constructor(
        public dialogRef: DialogRef<number | undefined>,
        @Inject(DIALOG_DATA) public data: RestoreWarningsDialogData
    ) {}

    public selectWarning(warning: RestoreWarningsDialogData['warnings'][number]): void {
        if (warning.node_id != null) {
            this.dialogRef.close(warning.node_id);
        }
    }
}

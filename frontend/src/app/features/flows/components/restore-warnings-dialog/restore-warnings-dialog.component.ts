import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, Inject } from '@angular/core';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';

import { RestoreWarning } from '../../models/graph.model';

export interface RestoreWarningsDialogData {
    warnings: RestoreWarning[];
    /** Where the warnings come from: an actual restore (default) or a read-only version preview. */
    context?: 'restore' | 'preview';
}

const RESTORE_MESSAGE =
    'Flow restored successfully, but it relies on dependencies that have since been deleted. Affected nodes require adaptation.';
const PREVIEW_MESSAGE =
    'This version relies on dependencies that have since been deleted. Affected nodes are shown without them.';

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

    protected get message(): string {
        return this.data.context === 'preview' ? PREVIEW_MESSAGE : RESTORE_MESSAGE;
    }

    public selectWarning(warning: RestoreWarningsDialogData['warnings'][number]): void {
        if (warning.node_id != null) {
            this.dialogRef.close(warning.node_id);
        }
    }
}

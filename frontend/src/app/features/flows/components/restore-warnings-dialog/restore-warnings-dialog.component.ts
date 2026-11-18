import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, Inject } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { StorageGrant } from '@shared/utils';

import { RestoreWarning } from '../../models/graph.model';

export interface RestoreWarningsDialogData {
    warnings: RestoreWarning[];
    /** Where the warnings come from: an actual restore (default) or a read-only version preview. */
    context?: 'restore' | 'preview';
}

const GRANT_LABELS: Record<StorageGrant, string> = { read: 'Read', write: 'Write', delete: 'Delete' };
const CODE_SLOT_LABELS: Record<string, string> = {
    pre_python_code: 'pre-computation',
    post_python_code: 'post-computation',
};

const RESTORE_MESSAGE =
    'Flow restored successfully, but it relies on dependencies that have since been deleted. Affected nodes require adaptation.';
const CAPPED_ONLY_MESSAGE =
    "Flow restored successfully, but some storage permissions of the restored code were unticked because you don't have the matching Files permissions.";
const MIXED_MESSAGE =
    "Flow restored successfully, but it relies on dependencies that have since been deleted, and some storage permissions were unticked because you don't have the matching Files permissions. Affected nodes require adaptation.";
const PREVIEW_MESSAGE =
    'This version relies on dependencies that have since been deleted. Affected nodes are shown without them.';

@Component({
    selector: 'app-restore-warnings-dialog',
    imports: [NgTemplateOutlet, AppSvgIconComponent, ButtonComponent, MatTooltip],
    templateUrl: './restore-warnings-dialog.component.html',
    styleUrl: './restore-warnings-dialog.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RestoreWarningsDialogComponent {
    constructor(
        public dialogRef: DialogRef<number | undefined>,
        @Inject(DIALOG_DATA) public data: RestoreWarningsDialogData
    ) {}

    protected get title(): string {
        if (this.cappedOnly) return 'Storage Permissions Reduced';
        return this.hasCapped ? 'Restore Warnings' : 'Missing Dependencies';
    }

    protected get message(): string {
        if (this.data.context === 'preview') return PREVIEW_MESSAGE;
        if (this.cappedOnly) return CAPPED_ONLY_MESSAGE;
        return this.hasCapped ? MIXED_MESSAGE : RESTORE_MESSAGE;
    }

    protected isCapped(warning: RestoreWarning): boolean {
        return warning.type === 'storage_grant_capped';
    }

    /** "Delete unticked — you don't have Files: Delete", naming the Classification Decision Table slot when it is one. */
    protected cappedText(warning: RestoreWarning): string {
        const grants = (warning.dropped_grants ?? []).map((grant) => GRANT_LABELS[grant]).join(', ');
        const missing = (warning.missing_permissions ?? []).join(', ');
        const slot = CODE_SLOT_LABELS[warning.field ?? ''];
        return `${grants} unticked${slot ? ` in ${slot} code` : ''} — you don't have ${missing}`;
    }

    private get hasCapped(): boolean {
        return this.data.warnings.some((warning) => this.isCapped(warning));
    }

    private get cappedOnly(): boolean {
        return this.data.warnings.length > 0 && this.data.warnings.every((warning) => this.isCapped(warning));
    }

    public selectWarning(warning: RestoreWarningsDialogData['warnings'][number]): void {
        if (warning.node_id != null) {
            this.dialogRef.close(warning.node_id);
        }
    }
}

import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, inject } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, CopyButtonComponent, JSON_EDITOR_OPTIONS, JsonEditorComponent } from '@shared/components';

export interface AuditValueDialogData {
    title: string;
    value: string;
    isPlainText: boolean;
}

const PLAIN_TEXT_EDITOR_OPTIONS = { ...JSON_EDITOR_OPTIONS, language: 'plaintext', readOnly: true };

@Component({
    selector: 'app-audit-value-dialog',
    imports: [AppSvgIconComponent, CopyButtonComponent, JsonEditorComponent, MatTooltipModule],
    templateUrl: './audit-value-dialog.component.html',
    styleUrls: ['./audit-value-dialog.component.scss'],
})
export class AuditValueDialogComponent {
    protected readonly data = inject<AuditValueDialogData>(DIALOG_DATA);
    protected readonly editorOptions = this.data.isPlainText ? PLAIN_TEXT_EDITOR_OPTIONS : JSON_EDITOR_OPTIONS;
    private readonly dialogRef = inject(DialogRef);

    protected close(): void {
        this.dialogRef.close();
    }
}

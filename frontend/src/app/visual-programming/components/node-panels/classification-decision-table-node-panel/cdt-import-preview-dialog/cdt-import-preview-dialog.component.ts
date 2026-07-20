import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';

import { CdtExportData } from '../cdt-export-import.service';

export type CdtImportPreviewResult = 'confirm' | 'cancel';

@Component({
    selector: 'app-cdt-import-preview-dialog',
    standalone: true,
    imports: [CommonModule, DialogModule],
    templateUrl: './cdt-import-preview-dialog.component.html',
    styleUrls: ['./cdt-import-preview-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtImportPreviewDialogComponent {
    private readonly dialogRef = inject<DialogRef<CdtImportPreviewResult>>(DialogRef);
    public readonly data = inject<CdtExportData>(DIALOG_DATA);

    public readonly conditionGroupCount = computed(() => this.data.condition_groups.length);
    public readonly promptCount = computed(() => this.data.prompt_configs.length);

    public readonly preCodeSummary = computed(() => this.summarizeCode(this.data.pre_python_code?.code));
    public readonly postCodeSummary = computed(() => this.summarizeCode(this.data.post_python_code?.code));

    public readonly groupRows = computed(() =>
        this.data.condition_groups.map((group) => ({
            name: group.group_name || '(unnamed)',
            routeCode: group.route_code || '—',
        }))
    );

    public confirm(): void {
        this.dialogRef.close('confirm');
    }

    public cancel(): void {
        this.dialogRef.close('cancel');
    }

    private summarizeCode(code: string | undefined): string {
        if (!code || code.trim().length === 0) {
            return 'empty';
        }
        const lineCount = code.split('\n').length;
        return `${lineCount} line${lineCount === 1 ? '' : 's'}`;
    }
}

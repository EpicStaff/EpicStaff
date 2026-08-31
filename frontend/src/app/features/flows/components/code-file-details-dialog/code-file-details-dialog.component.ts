import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

export interface CodeFileDetailsDialogData {
    entrypoint: string;
    libraries: string[];
}

@Component({
    selector: 'app-code-file-details-dialog',
    standalone: true,
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './code-file-details-dialog.component.html',
    styleUrls: ['./code-file-details-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CodeFileDetailsDialogComponent {
    readonly dialogRef = inject(DialogRef<void>);
    readonly data = inject<CodeFileDetailsDialogData>(DIALOG_DATA);

    readonly copied = signal(false);
    private copiedResetTimeout: ReturnType<typeof setTimeout> | null = null;

    get entrypointSignature(): string {
        return `def ${this.data.entrypoint}(...)`;
    }

    async copyEntrypoint(): Promise<void> {
        try {
            await navigator.clipboard.writeText(this.entrypointSignature);
            this.copied.set(true);
            if (this.copiedResetTimeout) clearTimeout(this.copiedResetTimeout);
            this.copiedResetTimeout = setTimeout(() => this.copied.set(false), 1500);
        } catch {}
    }

    close(): void {
        this.dialogRef.close();
    }
}

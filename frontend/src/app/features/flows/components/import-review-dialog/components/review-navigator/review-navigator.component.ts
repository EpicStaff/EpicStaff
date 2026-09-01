import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, inject, ViewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ReviewPythonCode } from '../../../../../../core/models/review-item.model';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyFieldComponent } from '../../../../../../shared/components/copy-field/copy-field.component';
import { CodeEditorComponent } from '../../../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import {
    CodeFileDetailsDialogComponent,
    CodeFileDetailsDialogData,
} from '../../../code-file-details-dialog/code-file-details-dialog.component';
import { CodeReviewableEntry } from '../../model/review-entry.model';
import { ReviewSessionStore } from '../../review-session.store';

@Component({
    selector: 'app-review-navigator',
    imports: [AppSvgIconComponent, MatTooltipModule, CodeEditorComponent, CopyFieldComponent],
    templateUrl: './review-navigator.component.html',
    styleUrls: ['./review-navigator.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReviewNavigatorComponent {
    protected readonly store = inject(ReviewSessionStore);
    private readonly dialog = inject(Dialog);

    @ViewChild('codeEditor') private codeEditorRef?: CodeEditorComponent;

    public librariesCount(code: ReviewPythonCode | undefined): number {
        return code?.libraries.split(/\s+/).filter(Boolean).length ?? 0;
    }

    private librariesList(code: ReviewPythonCode): string[] {
        return code.libraries.split(/\s+/).filter(Boolean);
    }

    public openFileDetails(entry: CodeReviewableEntry): void {
        this.dialog.open<void, CodeFileDetailsDialogData>(CodeFileDetailsDialogComponent, {
            data: {
                entrypoint: entry.code.entrypoint,
                libraries: this.librariesList(entry.code),
            },
        });
    }

    public copyCurrentCode(): void {
        this.codeEditorRef?.copyCode();
    }
}

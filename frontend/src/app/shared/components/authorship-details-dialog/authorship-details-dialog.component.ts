import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, inject } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AuthorshipFields } from '@shared/models';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { AuthorshipDetailsComponent } from '../authorship-details/authorship-details.component';

/** Authorship of any authored resource; `created_at` is null when the backend never recorded it. */
export interface AuthorshipDetailsSource extends AuthorshipFields {
    created_at: string | null;
}

export interface AuthorshipDetailsDialogData extends AuthorshipDetailsSource {
    /** Dialog heading, e.g. "Configuration Details" or "Tool Details". */
    title: string;
    /** Id of the heading element; the dialog is `aria-labelledby` it, so it must be unique per open dialog. */
    titleId: string;
}

/**
 * Read-only "Owner" / "Last editor" dialog shared by every authored resource.
 * Open it through {@link AuthorshipDetailsDialogService} rather than directly.
 */
@Component({
    selector: 'app-authorship-details-dialog',
    imports: [AppSvgIconComponent, MatTooltipModule, AuthorshipDetailsComponent],
    templateUrl: './authorship-details-dialog.component.html',
    styleUrls: ['./authorship-details-dialog.component.scss'],
})
export class AuthorshipDetailsDialogComponent {
    protected readonly data = inject<AuthorshipDetailsDialogData>(DIALOG_DATA);

    private readonly dialogRef = inject(DialogRef<void>);

    protected close(): void {
        this.dialogRef.close();
    }
}

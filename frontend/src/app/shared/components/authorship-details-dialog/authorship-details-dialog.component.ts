import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgComponentOutlet } from '@angular/common';
import { Component, inject, InputSignalWithTransform, Type } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AuthorshipFields } from '@shared/models';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { AuthorshipDetailsComponent } from '../authorship-details/authorship-details.component';

/** Authorship of any authored resource; `created_at` is null when the backend never recorded it. */
export interface AuthorshipDetailsSource extends AuthorshipFields {
    created_at: string | null;
}

/** What an `input()` signal reads and accepts; `never` for any other member. */
type SignalInputTypes<T> =
    T extends InputSignalWithTransform<infer ReadT, infer WriteT> ? { read: ReadT; write: WriteT } : never;

/**
 * The values to set on every `input()` signal of component `C`, keyed by input name and typed by what each
 * input accepts. Decorator `@Input()`s are not covered — extra content components use signal inputs.
 */
export type ComponentInputValues<C> = {
    [K in keyof C as [SignalInputTypes<C[K]>] extends [never] ? never : K]: SignalInputTypes<C[K]>['write'];
};

/**
 * Resource-specific details shown below the authorship block, after a divider — e.g. a collection's file
 * statistics. `inputs` must give every signal input of `component`, with matching types.
 */
export interface AuthorshipDetailsExtraContent<C = unknown> {
    component: Type<C>;
    inputs: ComponentInputValues<C>;
}

export interface AuthorshipDetailsDialogData extends AuthorshipDetailsSource {
    /** Dialog heading, e.g. "Configuration Details" or "Tool Details". */
    title: string;
    /** Id of the heading element; the dialog is `aria-labelledby` it, so it must be unique per open dialog. */
    titleId: string;
    extraContent?: AuthorshipDetailsExtraContent;
}

/**
 * Read-only "Owner" / "Last editor" dialog shared by every authored resource, optionally followed by
 * resource-specific details. Open it through {@link AuthorshipDetailsDialogService} rather than directly.
 */
@Component({
    selector: 'app-authorship-details-dialog',
    imports: [AppSvgIconComponent, MatTooltipModule, AuthorshipDetailsComponent, NgComponentOutlet],
    templateUrl: './authorship-details-dialog.component.html',
    styleUrls: ['./authorship-details-dialog.component.scss'],
})
export class AuthorshipDetailsDialogComponent {
    protected readonly data = inject<AuthorshipDetailsDialogData>(DIALOG_DATA);
    /** Already type-checked against the component by {@link AuthorshipDetailsExtraContent}; erased for the outlet. */
    protected readonly extraContentInputs: Record<string, unknown> | undefined = this.data.extraContent?.inputs;

    private readonly dialogRef = inject(DialogRef<void>);

    protected close(): void {
        this.dialogRef.close();
    }
}

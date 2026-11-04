import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    HostListener,
    inject,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, AuthorshipDetailsSource, AuthorshipFooterComponent } from '@shared/components';

import { GraphNoteModel } from '../../core/models/node.model';

export interface NoteEditDialogData {
    node: GraphNoteModel;
    /** Who created and who last edited the note; the dialog cannot read the editor's store itself. */
    authorship: AuthorshipDetailsSource;
}

@Component({
    selector: 'app-note-edit-dialog',
    imports: [FormsModule, AppSvgIconComponent, MatTooltipModule, AuthorshipFooterComponent],
    template: `
        <div class="dialog">
            <div class="header">
                <span class="title">
                    <app-svg-icon
                        icon="note"
                        size="1.25rem"
                    ></app-svg-icon>
                    Edit Note
                </span>

                <div class="actions">
                    <span
                        class="esc-label"
                        aria-hidden="true"
                        >ESC</span
                    >
                    <button
                        type="button"
                        class="close-button"
                        aria-label="Close"
                        matTooltip="Close"
                        matTooltipPosition="above"
                        (click)="close()"
                    >
                        <app-svg-icon icon="x"></app-svg-icon>
                    </button>
                </div>
            </div>

            <div class="body">
                <textarea
                    class="note-textarea"
                    [(ngModel)]="noteContent"
                    placeholder="Add note text..."
                    aria-label="Note text"
                    autofocus
                ></textarea>
            </div>

            <app-authorship-footer
                class="footer"
                [createdBy]="data.authorship.created_by"
                [createdAt]="data.authorship.created_at"
                [lastEditedBy]="data.authorship.last_edited_by"
                [lastEditedAt]="data.authorship.last_edited_at"
            />
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
                height: 100%;
            }

            .dialog {
                width: 100%;
                height: 100%;
                display: flex;
                flex-direction: column;
                background-color: var(--color-nodes-sidepanel-bg);
                border-radius: 12px;
                border: 1px solid var(--color-divider-subtle);
                overflow: hidden;
            }

            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 20px 40px;
                border-bottom: 1px solid var(--color-divider-subtle);
                flex-shrink: 0;
            }

            .title {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                font-size: 1.25rem;
                white-space: nowrap;
            }

            .title app-svg-icon {
                color: var(--accent-color, #4a6da7);
            }

            .actions {
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .esc-label {
                font-size: var(--text-body-small-large-size);
                color: #666;
                font-weight: var(--text-body-small-large-weight);
                padding: 0.15rem 0.3rem;
                border: 1px solid #444;
                border-radius: 4px;
                background: #2a2a2a;
            }

            .close-button {
                display: flex;
                padding: 0;
                border: none;
                background: none;
                color: inherit;
                font-size: 1.25rem;
                cursor: pointer;
                transition: all 0.2s ease;
                opacity: 0.8;
            }

            .close-button:is(:hover, :focus-visible) {
                opacity: 1;
                transform: scale(1.1);
                color: var(--accent-color, #4a6da7);
            }

            .body {
                flex: 1;
                display: flex;
                flex-direction: column;
                overflow: hidden;
                padding: 20px 40px;
            }

            .note-textarea {
                flex: 1;
                width: 100%;
                background-color: var(--color-input-background, #2a2a2a);
                border: 1px solid var(--color-input-border, #444);
                border-radius: 6px;
                padding: 0.75rem;
                color: #fff;
                font-size: 0.9375rem;
                line-height: 1.6;
                outline: none;
                transition: border-color 0.2s ease;
                font-family: inherit;
                resize: none;
            }

            .note-textarea:focus {
                border-color: var(--accent-color, #4a6da7);
            }

            .footer {
                flex-shrink: 0;
                padding: 20px 40px;
                border-top: 1px solid var(--color-divider-subtle);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NoteEditDialogComponent implements OnInit {
    noteContent = signal<string>('');

    public readonly dialogRef = inject<DialogRef<{ content: string }>>(DialogRef);
    public readonly data = inject<NoteEditDialogData>(DIALOG_DATA);
    private readonly cdr = inject(ChangeDetectorRef);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        // Initialize with the current note content
        this.noteContent.set(this.data.node.data.content || '');
        this.cdr.detectChanges();

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.close();
            }
        });
    }

    close(): void {
        this.dialogRef.close({ content: this.noteContent() });
    }

    // The host listener runs ahead of the tooltip of the focused control, which would take the first Escape;
    // the document one covers the focus being outside the dialog.
    @HostListener('keydown.escape', ['$event'])
    @HostListener('document:keydown.escape', ['$event'])
    onEsc(event: Event): void {
        if (event.defaultPrevented) return;
        event.stopPropagation();
        if (event instanceof KeyboardEvent) {
            event.preventDefault();
        }
        this.close();
    }
}

import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    HostListener,
    Inject,
    OnInit,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GraphNoteModel } from '../../core/models/node.model';

@Component({
    selector: 'app-note-edit-dialog',
    standalone: true,
    imports: [CommonModule, FormsModule, AppSvgIconComponent],
    template: `
        <div
            class="backdrop"
            (click)="close()"
        >
            <div
                class="wrapper"
                (click)="$event.stopPropagation()"
            >
                <div class="dialog-header">
                    <div class="icon-and-title">
                        <app-svg-icon
                            icon="note"
                            size="1.25rem"
                        ></app-svg-icon>
                        <h2 class="title">Edit Note</h2>
                    </div>
                    <div class="header-actions">
                        <div class="close-action">
                            <span class="esc-label">ESC</span>
                            <app-svg-icon
                                icon="x"
                                (click)="close()"
                                style="cursor:pointer"
                            ></app-svg-icon>
                        </div>
                    </div>
                </div>

                <div class="dialog-content">
                    <div class="form-group">
                        <textarea
                            class="note-textarea"
                            [(ngModel)]="noteContent"
                            placeholder="Add note text..."
                            autofocus
                        ></textarea>
                    </div>
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .wrapper {
                background-color: var(--color-modals-background, #1e1e1e);
                border-radius: 12px;
                color: var(--color-text-primary, #fff);
                width: 500px;
                max-width: 90vw;
                max-height: 85vh;
                display: flex;
                flex-direction: column;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            }

            .dialog-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 1.5rem;
                padding-bottom: 0.5rem;
            }

            .icon-and-title {
                display: flex;
                align-items: center;
                min-width: 0;
                gap: 0.75rem;
            }

            .icon-and-title app-svg-icon {
                color: var(--accent-color, #4a6da7);
            }

            .title {
                font-size: 1.125rem;
                font-weight: 600;
                margin: 0;
            }

            .header-actions {
                display: flex;
                align-items: center;
                gap: 1rem;
            }

            .close-action {
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .esc-label {
                font-size: 0.75rem;
                color: #666;
                font-weight: 500;
                padding: 0.15rem 0.3rem;
                border: 1px solid #444;
                border-radius: 4px;
                background: #2a2a2a;
            }

            .header-actions app-svg-icon {
                font-size: 1.25rem;
                cursor: pointer;
                transition: all 0.2s ease;
                opacity: 0.8;
            }

            .header-actions app-svg-icon:hover {
                opacity: 1;
                transform: scale(1.1);
                color: var(--accent-color, #4a6da7);
            }

            .dialog-content {
                flex: 1;
                overflow-y: auto;
                padding: 1.5rem;
                min-height: 200px;
            }

            .form-group {
                margin-bottom: 1rem;
                width: 100%;
            }

            .note-textarea {
                width: 100%;
                height: 250px;
                background-color: var(--color-input-background, #2a2a2a);
                border: 1px solid var(--color-input-border, #444);
                border-radius: 6px;
                padding: 0.625rem 0.75rem;
                color: #fff;
                font-size: 0.875rem;
                outline: none;
                transition: border-color 0.2s ease;
                font-family: inherit;
                resize: none;
            }

            .note-textarea:focus {
                border-color: var(--accent-color, #4a6da7);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NoteEditDialogComponent implements OnInit {
    noteContent: string = '';

    constructor(
        public dialogRef: DialogRef<{ content: string }>,
        @Inject(DIALOG_DATA) public data: { node: GraphNoteModel },
        private cdr: ChangeDetectorRef,
        private destroyRef: DestroyRef
    ) {}

    ngOnInit(): void {
        // Initialize with the current note content
        this.noteContent = this.data.node.data.content || '';
        this.cdr.detectChanges();

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.close();
            }
        });
    }

    close(): void {
        this.dialogRef.close({ content: this.noteContent });
    }

    @HostListener('document:keydown.escape', ['$event'])
    onEsc(event: Event): void {
        if (event instanceof KeyboardEvent) {
            event.preventDefault();
        }
        this.close();
    }
}

import { DOCUMENT } from '@angular/common';
import { Component, DestroyRef, ElementRef, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';
import { Observable } from 'rxjs';

export interface EntryCellEditorParams extends ICellEditorParams {
    // A popup textarea (the JSON value) instead of an in-cell input (the key).
    multiline: boolean;
    ariaLabel: string;
    placeholder: string;
    // The text to edit; for a value the list only previews, the full value is fetched first.
    text$: Observable<string>;
    // Why the last commit of this cell failed; the editor reopens with the rejected text.
    error: string | null;
    // Told on a commit whether the field still had focus: a commit by key keeps it, a click elsewhere took it.
    committed: (keptFocus: boolean) => void;
}

/**
 * Key and Value editor. The grid commits on Enter (key) or Tab / a click outside, and cancels on Esc; the value
 * textarea keeps Enter for new lines and commits on Ctrl/Cmd+Enter here.
 */
@Component({
    selector: 'app-entry-cell-editor',
    template: `
        @if (params.multiline) {
            <div class="entry-editor entry-editor--popup">
                <textarea
                    #field
                    class="entry-editor__field entry-editor__field--multiline"
                    spellcheck="false"
                    [value]="text()"
                    [readOnly]="loading()"
                    [placeholder]="loading() ? 'Loading…' : params.placeholder"
                    [attr.aria-label]="params.ariaLabel"
                    [attr.aria-busy]="loading()"
                    [attr.aria-invalid]="params.error ? true : null"
                    [attr.aria-describedby]="params.error ? errorId : hintId"
                    (input)="text.set(field.value)"
                    (keydown)="onTextareaKeydown($event)"
                ></textarea>
                @if (params.error) {
                    <p
                        class="entry-editor__error"
                        [id]="errorId"
                    >
                        {{ params.error }}
                    </p>
                } @else {
                    <p
                        class="entry-editor__hint"
                        [id]="hintId"
                    >
                        Ctrl+Enter to save · Esc to cancel
                    </p>
                }
            </div>
        } @else {
            <!-- With an error the key editor becomes a popup over its cell, so the reason shows as text below it. -->
            <div
                class="entry-editor"
                [class.entry-editor--popup]="!!params.error"
            >
                <input
                    #field
                    class="entry-editor__field"
                    maxlength="512"
                    [value]="text()"
                    [placeholder]="params.placeholder"
                    [attr.aria-label]="params.ariaLabel"
                    [attr.aria-invalid]="params.error ? true : null"
                    [attr.aria-describedby]="params.error ? errorId : null"
                    (input)="text.set(field.value)"
                />
                @if (params.error) {
                    <p
                        class="entry-editor__error"
                        [id]="errorId"
                    >
                        {{ params.error }}
                    </p>
                }
            </div>
        }
    `,
    styleUrls: ['./entry-cell-editor.component.scss'],
})
export class EntryCellEditorComponent implements ICellEditorAngularComp {
    private static nextId = 0;

    readonly field = viewChild<ElementRef<HTMLInputElement | HTMLTextAreaElement>>('field');

    readonly text = signal('');
    readonly loading = signal(true);

    protected params!: EntryCellEditorParams;
    protected readonly hintId = `entry-editor-hint-${++EntryCellEditorComponent.nextId}`;
    protected readonly errorId = `entry-editor-error-${EntryCellEditorComponent.nextId}`;

    private readonly destroyRef = inject(DestroyRef);
    private readonly document = inject(DOCUMENT);

    agInit(params: EntryCellEditorParams): void {
        this.params = params;
        params.text$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (text) => {
                this.text.set(text);
                this.loading.set(false);
            },
            // The grid reports the failure; nothing was loaded, so there is nothing to edit.
            error: () => params.stopEditing(true),
        });
    }

    // Focused at once, loading or not (read-only until then), so Esc cancels even before the value arrives.
    afterGuiAttached(): void {
        this.field()?.nativeElement.focus();
    }

    getValue(): string {
        return this.text();
    }

    // A commit before the full value arrived has nothing to save.
    isCancelAfterEnd(): boolean {
        this.params.committed(this.field()?.nativeElement === this.document.activeElement);
        return this.loading();
    }

    isPopup(): boolean {
        return this.params.multiline || !!this.params.error;
    }

    getPopupPosition(): 'over' {
        return 'over';
    }

    // Enter never reaches the grid, which would commit on it: plain Enter is a new line, Ctrl/Cmd+Enter commits.
    onTextareaKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Enter') return;
        event.stopPropagation();
        if (event.ctrlKey || event.metaKey) {
            event.preventDefault();
            this.params.stopEditing();
        }
    }
}

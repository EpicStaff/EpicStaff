import { DOCUMENT } from '@angular/common';
import { Component, DestroyRef, ElementRef, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { JSON_EDITOR_OPTIONS, JsonEditorComponent } from '@shared/components';
import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';
import type { editor as MonacoEditor } from 'monaco-editor';
import { Observable } from 'rxjs';

export interface EntryCellEditorParams extends ICellEditorParams {
    // A popup JSON editor (the value) instead of an in-cell input (the key).
    multiline: boolean;
    ariaLabel: string;
    placeholder: string;
    // The text to edit; for a value the list only previews, the full value is fetched first.
    text$: Observable<string>;
    // Why the last commit of this cell failed; the editor reopens with the rejected text.
    error: string | null;
    // Told on a commit whether the editor still had focus: a commit by key keeps it, a click elsewhere took it.
    committed: (keptFocus: boolean) => void;
}

// The parts of the Monaco namespace the loader puts on window that the key bindings need.
interface MonacoKeys {
    KeyCode: { Enter: number; Escape: number; Tab: number };
    KeyMod: { CtrlCmd: number; Shift: number };
}

// Monaco keeps these keys while one of its own widgets or a snippet is active: Esc closes the widget or leaves the
// snippet, Tab accepts a suggestion or moves to the next snippet placeholder.
const ESCAPE_TO_GRID = '!suggestWidgetVisible && !findWidgetVisible && !inSnippetMode';
const TAB_TO_GRID = '!suggestWidgetVisible && !inSnippetMode';
const EDITOR_HEIGHT_PX = 200;

/**
 * Key and Value editor. The key input commits on Enter (the grid's key); the value is the app's Monaco JSON editor,
 * where Enter is a new line, Ctrl/Cmd+Enter and Tab commit and Esc cancels. A click outside commits either.
 */
@Component({
    selector: 'app-entry-cell-editor',
    imports: [JsonEditorComponent],
    template: `
        @if (params.multiline) {
            <!-- Focusable, so Esc reaches the grid (cancel) while the value or Monaco is still loading. -->
            <div
                #root
                class="entry-editor entry-editor--popup entry-editor--json"
                role="group"
                tabindex="-1"
                [attr.aria-label]="params.ariaLabel"
                [attr.aria-busy]="loading()"
                [attr.aria-describedby]="params.error ? errorId : hintId"
                (keydown)="onValueKeydown($event)"
            >
                @if (loading()) {
                    <p
                        class="entry-editor__loading"
                        [style.height.px]="editorHeight"
                    >
                        Loading…
                    </p>
                } @else {
                    <app-json-editor
                        title="Value"
                        [jsonData]="initialText()"
                        [editorHeight]="editorHeight"
                        [editorOptions]="editorOptions"
                        (editorReady)="onEditorReady($event)"
                    />
                }
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
                #root
                class="entry-editor"
                [class.entry-editor--popup]="!!params.error"
            >
                <input
                    #input
                    class="entry-editor__input"
                    maxlength="512"
                    [value]="text()"
                    [placeholder]="params.placeholder"
                    [attr.aria-label]="params.ariaLabel"
                    [attr.aria-invalid]="params.error ? true : null"
                    [attr.aria-describedby]="params.error ? errorId : null"
                    (input)="text.set(input.value)"
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

    private readonly root = viewChild<ElementRef<HTMLElement>>('root');
    private readonly input = viewChild<ElementRef<HTMLInputElement>>('input');

    // The key input's text, and the value's until Monaco is up (from then on the editor itself is read).
    readonly text = signal('');
    readonly loading = signal(true);
    // What the JSON editor opens with.
    protected readonly initialText = signal('');

    protected params!: EntryCellEditorParams;
    protected readonly hintId = `entry-editor-hint-${++EntryCellEditorComponent.nextId}`;
    protected readonly errorId = `entry-editor-error-${EntryCellEditorComponent.nextId}`;
    protected readonly editorHeight = EDITOR_HEIGHT_PX;
    protected editorOptions!: MonacoEditor.IStandaloneEditorConstructionOptions;

    private monacoEditor: MonacoEditor.IStandaloneCodeEditor | null = null;
    private readonly destroyRef = inject(DestroyRef);
    private readonly document = inject(DOCUMENT);

    agInit(params: EntryCellEditorParams): void {
        this.params = params;
        this.editorOptions = {
            ...JSON_EDITOR_OPTIONS,
            ariaLabel: params.ariaLabel,
            // Suggest and hover widgets are placed on the page, not clipped by the popup or the grid.
            fixedOverflowWidgets: true,
        };
        params.text$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (text) => {
                this.text.set(text);
                this.initialText.set(text);
                this.loading.set(false);
            },
            // The grid reports the failure; nothing was loaded, so there is nothing to edit.
            error: () => params.stopEditing(true),
        });
    }

    // Focused at once, loading or not, so Esc cancels even before the value (or Monaco) arrives.
    afterGuiAttached(): void {
        (this.input() ?? this.root())?.nativeElement.focus();
    }

    // Monaco's own text, not the last change it reported: the JSON editor ignores edits made while it formats the
    // value it opened with, so they would otherwise be lost.
    getValue(): string {
        return this.monacoEditor?.getValue() ?? this.text();
    }

    // A commit before the full value arrived has nothing to save.
    isCancelAfterEnd(): boolean {
        this.params.committed(!!this.root()?.nativeElement.contains(this.document.activeElement));
        return this.loading();
    }

    isPopup(): boolean {
        return this.params.multiline || !!this.params.error;
    }

    getPopupPosition(): 'over' {
        return 'over';
    }

    // Actions, not commands: an action's keys work in this editor only and go with it, a command's in every Monaco
    // editor on the page for good. They win over Monaco's defaults and keep the key from the grid; Tab (Monaco's
    // indent) and Esc (which it takes while there is a selection) are handed back to the grid, which commits or
    // cancels on them.
    protected onEditorReady(editor: MonacoEditor.IStandaloneCodeEditor): void {
        this.monacoEditor = editor;
        // The JSON editor opens '' (a rejected empty value) as '{}'; show what a commit would save.
        if (!this.initialText()) editor.setValue('');
        const monaco = (window as unknown as { monaco?: MonacoKeys }).monaco;
        if (monaco) {
            const { KeyCode, KeyMod } = monaco;
            const actions: MonacoEditor.IActionDescriptor[] = [
                {
                    id: 'entry-editor.commit',
                    label: 'Save value',
                    keybindings: [KeyMod.CtrlCmd | KeyCode.Enter],
                    run: () => this.params.stopEditing(),
                },
                {
                    id: 'entry-editor.cancel',
                    label: 'Cancel editing',
                    keybindings: [KeyCode.Escape],
                    keybindingContext: ESCAPE_TO_GRID,
                    run: () => this.passToGrid({ key: 'Escape' }),
                },
                {
                    id: 'entry-editor.next-cell',
                    label: 'Save value and go to the next cell',
                    keybindings: [KeyCode.Tab],
                    keybindingContext: TAB_TO_GRID,
                    run: () => this.passToGrid({ key: 'Tab' }),
                },
                {
                    id: 'entry-editor.previous-cell',
                    label: 'Save value and go to the previous cell',
                    keybindings: [KeyMod.Shift | KeyCode.Tab],
                    keybindingContext: TAB_TO_GRID,
                    run: () => this.passToGrid({ key: 'Tab', shiftKey: true }),
                },
            ];
            const bindings = actions.map((action) => editor.addAction(action));
            this.destroyRef.onDestroy(() => bindings.forEach((binding) => binding.dispose()));
        }
        editor.focus();
    }

    // Enter never reaches the grid, which would commit on it: plain Enter is Monaco's new line, Ctrl/Cmd+Enter
    // commits (here only while Monaco is not up yet; once it is, its own binding takes the key first).
    protected onValueKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Enter') return;
        event.stopPropagation();
        if (event.ctrlKey || event.metaKey) {
            event.preventDefault();
            this.params.stopEditing();
        }
    }

    // The cell's own key handling, which the popup would have given the key to had Monaco not taken it. (The
    // params' stopEditing cannot cancel: its argument only suppresses navigation.)
    private passToGrid(key: KeyboardEventInit): void {
        this.params.onKeyDown(new KeyboardEvent('keydown', { ...key, bubbles: true, cancelable: true }));
    }
}

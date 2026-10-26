import { Component, computed, DestroyRef, ElementRef, inject, input, NgZone } from '@angular/core';
import type { editor as MonacoEditor } from 'monaco-editor';
import { DiffEditorComponent, DiffEditorModel } from 'ngx-monaco-editor-v2';

const LANGUAGE = 'python';

/**
 * Inline (one column, removed lines above added ones): a side-by-side view has no room in a node panel. Both sides
 * read-only. Every whitespace difference is shown, as indentation is meaning in Python and the field mark counts it
 * too. Unchanged blocks are folded ("N hidden lines", opened on click). The theme is the code editor's.
 */
const DIFF_EDITOR_OPTIONS: MonacoEditor.IStandaloneDiffEditorConstructionOptions = {
    theme: 'vs-dark',
    renderSideBySide: false,
    useInlineViewWhenSpaceIsLimited: false,
    readOnly: true,
    originalEditable: false,
    ignoreTrimWhitespace: false,
    hideUnchangedRegions: { enabled: true },
    renderMarginRevertIcon: false,
    renderGutterMenu: false,
    renderOverviewRuler: false,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    wrappingIndent: 'indent',
    // Laid out by the observer below when the view's size changes.
    automaticLayout: false,
};

/**
 * A changed code as an inline diff, read-only: the current canvas code is the original (removed lines), the
 * version's code the modified side (added lines), so it reads as what a restore does. It fills its host, which
 * needs a height of its own. The editor is built again only when one of the two codes changes.
 */
@Component({
    selector: 'app-code-diff-view',
    imports: [DiffEditorComponent],
    template: `
        <ngx-monaco-diff-editor
            class="code-diff-view__editor"
            [options]="options"
            [originalModel]="originalModel()"
            [modifiedModel]="modifiedModel()"
            (onInit)="onEditorInit($event)"
        />
    `,
    styleUrls: ['./code-diff-view.component.scss'],
    host: {
        role: 'region',
        'aria-label': 'Code changes: current canvas code compared with this version',
    },
})
export class CodeDiffViewComponent {
    /** The code on the canvas now. */
    readonly current = input.required<string>();
    /** The code of the previewed version. */
    readonly version = input.required<string>();

    // A new model rebuilds the editor, so each depends on its own code only.
    protected readonly originalModel = computed<DiffEditorModel>(() => ({ code: this.current(), language: LANGUAGE }));
    protected readonly modifiedModel = computed<DiffEditorModel>(() => ({ code: this.version(), language: LANGUAGE }));

    protected readonly options = DIFF_EDITOR_OPTIONS;

    private editor: MonacoEditor.IStandaloneDiffEditor | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly zone = inject(NgZone);

    constructor() {
        inject(DestroyRef).onDestroy(() => this.resizeObserver?.disconnect());
    }

    /** Called again for each rebuilt editor. */
    protected onEditorInit(editor: MonacoEditor.IStandaloneDiffEditor): void {
        this.editor = editor;
        if (this.resizeObserver) return;
        this.zone.runOutsideAngular(() => {
            this.resizeObserver = new ResizeObserver(() => this.editor?.layout());
            this.resizeObserver.observe(this.host.nativeElement);
        });
    }
}

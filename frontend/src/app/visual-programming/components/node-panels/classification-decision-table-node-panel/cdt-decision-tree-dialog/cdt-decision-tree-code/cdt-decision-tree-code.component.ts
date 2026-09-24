import { ChangeDetectionStrategy, Component, computed, effect, input, signal } from '@angular/core';

import {
    ensureMonacoLoaded,
    monacoEditorApi,
} from '../../classification-decision-table-grid/shared/monaco-loader.util';

/** One rendered line: its number, its source, and its colouring once it arrives. */
interface CdtCodeRow {
    readonly number: number;
    readonly text: string;
    /** Colourised HTML for this line, or null while plain text is being shown. */
    readonly html: string | null;
}

/**
 * Read-only source, with line numbers for code and neither for prose.
 *
 * Colouring comes from `monaco.editor.colorize()` — highlighted HTML with no
 * editor instance behind it, the same route the grid's code cells take. An editor
 * would bring a scroll container, a keyboard surface and a context menu into a
 * panel whose whole point is that nothing here can be edited.
 *
 * Plain text renders first and is replaced when the colouring resolves, so a
 * Monaco bundle that is slow or absent degrades to readable text rather than to
 * an empty box.
 */
@Component({
    selector: 'app-cdt-decision-tree-code',
    standalone: true,
    templateUrl: './cdt-decision-tree-code.component.html',
    styleUrls: ['./cdt-decision-tree-code.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeCodeComponent {
    public readonly body = input.required<string>();
    public readonly language = input.required<'python' | 'text'>();

    /**
     * Carries the body it was produced from, so a stale result cannot colour the
     * next block's source. That also keeps the effect free of synchronous signal
     * writes — the only write happens in the promise callback.
     */
    private readonly colorized = signal<{ readonly body: string; readonly lines: readonly string[] } | null>(null);

    protected readonly rows = computed<readonly CdtCodeRow[]>(() => {
        const lines = this.body().split('\n');
        const done = this.colorized();
        const html = done && done.body === this.body() ? done.lines : null;

        // Length has to agree, or the numbers would label the wrong lines. A
        // mismatch means the split misread Monaco's output; plain text is the
        // honest fallback.
        const usable = html && html.length === lines.length ? html : null;

        return lines.map((text, index) => ({ number: index + 1, text, html: usable ? usable[index] : null }));
    });

    constructor() {
        effect(() => {
            const body = this.body();

            // Prose is shown verbatim: `colorize` would tokenise `{{var}}` and
            // ordinary sentences as if they were code.
            if (this.language() !== 'python' || !body) return;

            ensureMonacoLoaded().then(() => {
                const editor = monacoEditorApi();
                if (!editor?.colorize) return;

                // The `mtk*` classes `colorize` emits are only defined once a theme
                // is applied. `vs-dark` matches every other Monaco surface here.
                editor.setTheme?.('vs-dark');

                editor
                    .colorize(body, 'python', { tabSize: 4 })
                    .then((html) => {
                        // Two colorize promises can be in flight on one instance —
                        // a block swap changes the inputs and destroys nothing. An
                        // older one settling last would park the previous block's
                        // colouring, and the reader would then fall back to plain
                        // text for good: the effect never re-runs for this body.
                        if (this.body() !== body) return;
                        this.colorized.set({ body, lines: splitColorizedLines(restoreSpaces(html)) });
                    })
                    .catch(() => undefined);
            });
        });
    }
}

/**
 * Turn Monaco's non-breaking spaces back into ordinary ones.
 *
 * `colorize` emits U+00A0 per space and a run of them per tab, for a view with no
 * `white-space: pre`. Left alone, copying the block yields non-breaking spaces for
 * every Python indent and pasting raises an IndentationError with no visible
 * cause. This block *is* `white-space: pre`, so plain spaces render identically.
 *
 * Blanket replace is safe: colorize emits only `class`, `dir` and `style`, and no
 * value of those can contain U+00A0.
 */
function restoreSpaces(html: string): string {
    return html.replace(/\u00a0/g, ' ').replace(/&nbsp;/g, ' ');
}

/**
 * `colorize` returns the whole text in one pass, lines joined by `<br/>`.
 *
 * Colouring line by line would restart the tokeniser per line and lose the state a
 * multi-line string carries, so the split happens after the fact. Monaco closes
 * every span before each break, which is what makes that safe.
 */
function splitColorizedLines(html: string): readonly string[] {
    const parts = html.split(/<br\s*\/?>/);

    // The last line is terminated by a break as well, leaving an empty part that
    // is not a line of source.
    if (parts.length > 1 && parts[parts.length - 1] === '') parts.pop();

    return parts;
}

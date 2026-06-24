import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    input,
    OnInit,
    output,
    signal,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CDT_COLUMN_KIND } from '../../cdt.constants';
import { filterByQuery } from '../../cdt-search-filter.util';

export type ExpressionBuilderMode = 'expression' | 'manipulation';

export type TokenCategory = 'primary' | 'logical' | 'keyword' | 'comparison' | 'math';

export interface Token {
    label: string; // text shown on the toolbar chip
    insert: string; // text inserted into the expression (Python form)
    category: TokenCategory;
}

const EXPRESSION_TOKENS: Token[] = [
    { label: '@', insert: '@', category: 'primary' },
    { label: 'AND', insert: 'and', category: 'logical' },
    { label: 'NOT', insert: 'not', category: 'logical' },
    { label: 'IN', insert: 'in', category: 'logical' },
    { label: 'IS', insert: 'is', category: 'logical' },
    { label: 'TRUE', insert: 'True', category: 'keyword' },
    { label: 'FALSE', insert: 'False', category: 'keyword' },
    { label: 'NONE', insert: 'None', category: 'keyword' },
    { label: '>', insert: '>', category: 'comparison' },
    { label: '<', insert: '<', category: 'comparison' },
    { label: '==', insert: '==', category: 'comparison' },
    { label: '!=', insert: '!=', category: 'comparison' },
    { label: '>=', insert: '>=', category: 'comparison' },
    { label: '<=', insert: '<=', category: 'comparison' },
];

const MANIPULATION_TOKENS: Token[] = [
    { label: '@', insert: '@', category: 'primary' },
    { label: '+', insert: '+', category: 'math' },
    { label: '-', insert: '-', category: 'math' },
    { label: '/', insert: '/', category: 'math' },
    { label: '*', insert: '*', category: 'math' },
    { label: '()', insert: '()', category: 'math' },
    { label: '%', insert: '%', category: 'math' },
    { label: '//', insert: '//', category: 'math' },
    { label: '**', insert: '**', category: 'math' },
    { label: '=', insert: '=', category: 'math' },
];

const EXPRESSION_TEMPLATES = ['Required field', 'Range of values', 'After a point'];
const MANIPULATION_TEMPLATES = ['Combined', 'Percentage', 'Average'];
const EXPRESSION_TEMPLATE_EXAMPLES: Record<string, string> = {
    'Required field': '# @field  Required field',
    'Range of values': '# 10<=@field<=100  Range of values',
    'After a point': '# @field>=10  After a point',
};
const MANIPULATION_TEMPLATE_EXAMPLES: Record<string, string> = {
    Combined: '# @field=(@field1 + @field2)*@field3  Combined',
    Percentage: '# @field=(@field1 / @field2) * 100  Percentage',
    Average: '# @field=(@field1 + @field2 + @field3) / 3  Average',
};

/** Tokens that are symbolic — inserted without surrounding spaces. */
const SYMBOLIC_TOKENS = new Set([
    '@',
    '()',
    '>',
    '<',
    '==',
    '!=',
    '>=',
    '<=',
    '+',
    '-',
    '/',
    '*',
    '%',
    '//',
    '**',
    '=',
]);

@Component({
    selector: 'app-expression-builder',
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [CommonModule, FormsModule],
    templateUrl: './expression-builder.component.html',
    styleUrls: ['./expression-builder.component.scss'],
})
export class ExpressionBuilderComponent implements OnInit {
    // ── Inputs ────────────────────────────────────────────────────────────────
    value = input<string>('');
    variables = input<string[]>([]);
    mode = input<ExpressionBuilderMode>(CDT_COLUMN_KIND.EXPRESSION);

    // ── Outputs ───────────────────────────────────────────────────────────────
    commit = output<string>();
    cancel = output<void>();
    valueChange = output<string>();

    // ── Editor ────────────────────────────────────────────────────────────────
    @ViewChild('editor') editorRef!: ElementRef<HTMLTextAreaElement>;

    displayValue = signal<string>('');

    /** Read-only tip lines rendered above the textarea (ephemeral — never saved). */
    readonly tips = signal<string[]>([]);

    /** Last known caret position — updated on every input/click/keyup. */
    private caretPos = 0;

    // ── Search / right panel ──────────────────────────────────────────────────
    searchTerm = signal<string>('');

    filteredVars = computed(() => filterByQuery(this.variables(), this.searchTerm(), (v) => v));

    // ── Inline @ typeahead ────────────────────────────────────────────────────
    mentionActive = signal<boolean>(false);
    mentionQuery = signal<string>('');
    mentionIndex = signal<number>(0);
    readonly mentionTop = signal(0);
    readonly mentionLeft = signal(0);

    filteredMention = computed(() => {
        const q = this.mentionQuery().toLowerCase();
        return this.variables().filter((v) => v.toLowerCase().startsWith(q));
    });

    // ── Toolbar / templates ───────────────────────────────────────────────────
    tokens = computed<Token[]>(() =>
        this.mode() === CDT_COLUMN_KIND.EXPRESSION ? EXPRESSION_TOKENS : MANIPULATION_TOKENS
    );

    templates = computed<string[]>(() =>
        this.mode() === CDT_COLUMN_KIND.EXPRESSION ? EXPRESSION_TEMPLATES : MANIPULATION_TEMPLATES
    );

    // ── Lifecycle ─────────────────────────────────────────────────────────────
    constructor() {
        // When the bound value input changes, sync displayValue.
        effect(() => {
            const v = this.value();
            this.displayValue.set(v);
        });
    }

    ngOnInit(): void {
        this.displayValue.set(this.value());
    }

    // ── Textarea event handlers ───────────────────────────────────────────────

    onInput(event: Event): void {
        const ta = event.target as HTMLTextAreaElement;
        this.displayValue.set(ta.value);
        this.caretPos = ta.selectionStart ?? 0;
        this.updateMentionState(ta);
        this.valueChange.emit(ta.value);
    }

    onKeydown(event: KeyboardEvent): void {
        if (this.mentionActive()) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                const max = this.filteredMention().length - 1;
                this.mentionIndex.update((i) => Math.min(i + 1, max));
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                this.mentionIndex.update((i) => Math.max(i - 1, 0));
                return;
            }
            if (event.key === 'Enter') {
                event.preventDefault();
                const chosen = this.filteredMention()[this.mentionIndex()];
                if (chosen) this.selectMention(chosen);
                return;
            }
            if (event.key === 'Escape') {
                this.mentionActive.set(false);
                return;
            }
        }

        if (event.key === 'Enter') {
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                this.commit.emit(this.displayValue());
            }
            return;
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            this.cancel.emit();
        }
    }

    onCaretUpdate(event: Event): void {
        const ta = event.target as HTMLTextAreaElement;
        this.caretPos = ta.selectionStart ?? 0;
    }

    // ── Token insertion ───────────────────────────────────────────────────────

    insertToken(token: string): void {
        const ta = this.editorRef?.nativeElement;
        const pos = ta ? (ta.selectionStart ?? this.caretPos) : this.caretPos;
        const current = this.displayValue();

        let insertion: string;
        if (SYMBOLIC_TOKENS.has(token)) {
            insertion = token === '()' ? '()' : token;
        } else {
            // Word tokens: surround with spaces (trimmed at boundaries).
            insertion = ` ${token} `;
        }

        const before = current.slice(0, pos);
        const after = current.slice(pos);
        const next = before + insertion + after;
        this.displayValue.set(next);
        this.valueChange.emit(next);

        // Restore focus and advance caret.
        if (ta) {
            ta.value = next;
            const newPos = pos + insertion.length;
            requestAnimationFrame(() => {
                ta.setSelectionRange(newPos, newPos);
                ta.focus();
            });
            this.caretPos = pos + insertion.length;
        }
    }

    insertVariable(varName: string): void {
        const insertion = `@${varName} `;
        const ta = this.editorRef?.nativeElement;
        const pos = ta ? (ta.selectionStart ?? this.caretPos) : this.caretPos;
        const current = this.displayValue();
        const next = current.slice(0, pos) + insertion + current.slice(pos);
        this.displayValue.set(next);
        this.valueChange.emit(next);

        if (ta) {
            ta.value = next;
            const newPos = pos + insertion.length;
            requestAnimationFrame(() => {
                ta.setSelectionRange(newPos, newPos);
                ta.focus();
            });
            this.caretPos = newPos;
        }
    }

    // ── Quick template insertion ──────────────────────────────────────────────

    /**
     * Returns true when the given template label has an example defined,
     * so the template button can be enabled in the template.
     */
    hasTemplateExample(tpl: string): boolean {
        const map =
            this.mode() === CDT_COLUMN_KIND.EXPRESSION ? EXPRESSION_TEMPLATE_EXAMPLES : MANIPULATION_TEMPLATE_EXAMPLES;
        return tpl in map;
    }

    onTemplateClick(tpl: string): void {
        const map =
            this.mode() === CDT_COLUMN_KIND.EXPRESSION ? EXPRESSION_TEMPLATE_EXAMPLES : MANIPULATION_TEMPLATE_EXAMPLES;
        const example = map[tpl];
        if (!example) return;

        // Append the tip line to the read-only tips block above the textarea.
        this.tips.update((current) => [...current, example]);

        // Focus the writable textarea — do not touch displayValue or caret.
        const ta = this.editorRef?.nativeElement;
        if (ta) {
            requestAnimationFrame(() => ta.focus());
        }
    }

    dismissTip(index: number): void {
        this.tips.update((current) => current.filter((_, i) => i !== index));
    }

    // ── @ typeahead helpers ───────────────────────────────────────────────────

    private updateMentionState(ta: HTMLTextAreaElement): void {
        const pos = ta.selectionStart ?? 0;
        const text = ta.value.slice(0, pos);
        // Walk back from cursor to find an @ not preceded by a word char.
        const match = text.match(/@([\w]*)$/);
        if (match) {
            this.mentionQuery.set(match[1]);
            this.mentionActive.set(true);
            this.mentionIndex.set(0);

            const coords = this.getCaretCoordinates(ta, pos);
            const lineHeight = parseFloat(window.getComputedStyle(ta).lineHeight) || 18;
            this.mentionTop.set(coords.top + lineHeight + ta.offsetTop);
            this.mentionLeft.set(coords.left + ta.offsetLeft);
        } else {
            this.mentionActive.set(false);
        }
    }

    private getCaretCoordinates(ta: HTMLTextAreaElement, position: number): { top: number; left: number } {
        const style = window.getComputedStyle(ta);
        const mirror = document.createElement('div');
        const propsToCopy: string[] = [
            'box-sizing',
            'width',
            'height',
            'overflow-x',
            'overflow-y',
            'border-top-width',
            'border-right-width',
            'border-bottom-width',
            'border-left-width',
            'border-style',
            'padding-top',
            'padding-right',
            'padding-bottom',
            'padding-left',
            'font-style',
            'font-variant',
            'font-weight',
            'font-stretch',
            'font-size',
            'font-size-adjust',
            'line-height',
            'font-family',
            'text-align',
            'text-transform',
            'text-indent',
            'text-decoration',
            'letter-spacing',
            'word-spacing',
            'tab-size',
            '-moz-tab-size',
            'white-space',
            'word-wrap',
            'word-break',
        ];
        for (const p of propsToCopy) {
            mirror.style.setProperty(p, style.getPropertyValue(p));
        }
        mirror.style.position = 'absolute';
        mirror.style.visibility = 'hidden';
        mirror.style.top = '0';
        mirror.style.left = '0';
        mirror.style.whiteSpace = 'pre-wrap';
        mirror.style.wordWrap = 'break-word';

        document.body.appendChild(mirror);

        mirror.textContent = ta.value.substring(0, position);
        const span = document.createElement('span');
        span.textContent = ta.value.substring(position) || '.';
        mirror.appendChild(span);

        const spanRect = span.getBoundingClientRect();
        const mirrorRect = mirror.getBoundingClientRect();

        const top = spanRect.top - mirrorRect.top - ta.scrollTop;
        const left = spanRect.left - mirrorRect.left - ta.scrollLeft;

        document.body.removeChild(mirror);

        return { top, left };
    }

    selectMention(varName: string): void {
        const ta = this.editorRef?.nativeElement;
        if (!ta) return;
        const pos = ta.selectionStart ?? 0;
        const text = ta.value;
        // Find the @ that started the mention.
        const before = text.slice(0, pos);
        const replaced = before.replace(/@([\w]*)$/, `@${varName} `);
        const next = replaced + text.slice(pos);
        this.displayValue.set(next);
        this.valueChange.emit(next);
        ta.value = next;
        const newPos = replaced.length;
        requestAnimationFrame(() => {
            ta.setSelectionRange(newPos, newPos);
            ta.focus();
        });
        this.caretPos = newPos;
        this.mentionActive.set(false);
    }

    closeMention(): void {
        this.mentionActive.set(false);
    }
}

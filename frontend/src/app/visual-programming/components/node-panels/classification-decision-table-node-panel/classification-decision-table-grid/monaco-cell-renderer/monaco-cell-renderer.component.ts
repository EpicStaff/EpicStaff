import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    inject,
    OnDestroy,
    ViewChild,
    ViewEncapsulation,
} from '@angular/core';
import { ICellRendererParams } from 'ag-grid-community';

import { BaseCellRenderer } from '../shared/base-cell-renderer';

interface MonacoWindow extends Window {
    monaco?: {
        editor?: {
            colorize?: (text: string, lang: string, opts: Record<string, unknown>) => Promise<string>;
            setTheme?: (theme: string) => void;
        };
    };
    require?: { config?: (opts: Record<string, unknown>) => void } & ((deps: string[], cb: () => void) => void);
}

// Shared singleton Monaco loader — ensures Monaco is loaded exactly once
let monacoLoadPromise: Promise<void> | null = null;

function ensureMonacoLoaded(): Promise<void> {
    if ((window as unknown as MonacoWindow).monaco?.editor?.colorize) {
        return Promise.resolve();
    }
    if (monacoLoadPromise) {
        return monacoLoadPromise;
    }
    monacoLoadPromise = new Promise<void>((resolve) => {
        const win = window as unknown as MonacoWindow;
        // If the AMD loader is already present (ngx-monaco-editor loaded it)
        if (win.require?.config) {
            win.require.config({ paths: { vs: 'assets/monaco/min/vs' } });
            win.require(['vs/editor/editor.main'], () => resolve());
            return;
        }
        // Otherwise, load the AMD loader script first
        const script = document.createElement('script');
        script.src = 'assets/monaco/min/vs/loader.js';
        script.onload = () => {
            win.require!.config!({ paths: { vs: 'assets/monaco/min/vs' } });
            win.require!(['vs/editor/editor.main'], () => resolve());
        };
        script.onerror = () => {
            monacoLoadPromise = null; // allow retry
            resolve(); // resolve anyway so cells fall back to plain text
        };
        document.head.appendChild(script);
    });
    return monacoLoadPromise;
}

@Component({
    selector: 'app-monaco-cell-renderer',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div
            class="code-cell"
            #codeContainer
        >
            <span
                *ngIf="!value"
                class="placeholder"
                >—</span
            >
            <span
                *ngIf="value && !colorized"
                class="plain-text"
                >{{ displayText }}</span
            >
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
                height: 100%;
            }
            .code-cell {
                width: 100%;
                height: 100%;
                overflow: hidden;
                display: flex;
                align-items: center;
                padding: 0 8px;
                cursor: text;
                font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
                font-size: 12px;
                line-height: 1.4;
                color: #d4d4d4;
            }
            .plain-text {
                color: #d4d4d4;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .placeholder {
                color: rgba(255, 255, 255, 0.2);
            }
            .colorized-code {
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                display: inline;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    encapsulation: ViewEncapsulation.None,
})
export class MonacoCellRendererComponent
    extends BaseCellRenderer<ICellRendererParams>
    implements AfterViewInit, OnDestroy
{
    @ViewChild('codeContainer', { static: true }) codeContainer!: ElementRef<HTMLDivElement>;

    private cdr = inject(ChangeDetectorRef);

    public value: string = '';
    public displayText: string = '';
    public colorized = false;
    private destroyed = false;

    override agInit(params: ICellRendererParams): void {
        this.value = params.value || '';
        this.updateDisplayText();
        ensureMonacoLoaded();
    }

    override refresh(params: ICellRendererParams): boolean {
        const newValue = params.value || '';
        if (newValue !== this.value) {
            this.value = newValue;
            this.colorized = false;
            this.updateDisplayText();
            this.tryColorize();
            this.cdr.markForCheck();
        }
        return true;
    }

    ngAfterViewInit(): void {
        this.tryColorize();
    }

    ngOnDestroy(): void {
        this.destroyed = true;
    }

    private updateDisplayText(): void {
        if (!this.value) {
            this.displayText = '';
            return;
        }
        const firstLine = this.value.split('\n')[0].trim();
        this.displayText = this.value.includes('\n') ? firstLine + ' …' : firstLine;
    }

    private tryColorize(): void {
        if (!this.value || this.colorized) return;

        ensureMonacoLoaded().then(() => {
            if (this.destroyed || this.colorized || !this.value) return;

            const monaco = (window as unknown as MonacoWindow).monaco;
            if (!monaco?.editor?.colorize) return;

            // Ensure vs-dark theme is active (matches the Monaco editors elsewhere)
            monaco.editor?.setTheme?.('vs-dark');

            const firstLine = this.value.split('\n')[0].trim();
            const suffix = this.value.includes('\n') ? '<span style="color:rgba(255,255,255,0.3)"> …</span>' : '';

            monaco.editor.colorize(firstLine, 'python', { tabSize: 4 }).then((html: string) => {
                if (!this.destroyed && this.codeContainer?.nativeElement) {
                    this.codeContainer.nativeElement.innerHTML = `<span class="colorized-code">${html}${suffix}</span>`;
                    this.colorized = true;
                    this.cdr.markForCheck();
                }
            });
        });
    }
}

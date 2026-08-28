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
import { ensureMonacoLoaded, monacoEditorApi } from '../shared/monaco-loader.util';

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

            const editor = monacoEditorApi();
            if (!editor?.colorize) return;

            // Ensure vs-dark theme is active (matches the Monaco editors elsewhere)
            editor.setTheme?.('vs-dark');

            const firstLine = this.value.split('\n')[0].trim();
            const suffix = this.value.includes('\n') ? '<span style="color:rgba(255,255,255,0.3)"> …</span>' : '';

            editor
                .colorize(firstLine, 'python', { tabSize: 4 })
                .then((html: string) => {
                    if (!this.destroyed && this.codeContainer?.nativeElement) {
                        this.codeContainer.nativeElement.innerHTML = `<span class="colorized-code">${html}${suffix}</span>`;
                        this.colorized = true;
                        this.cdr.markForCheck();
                    }
                })
                // `colorize` rejects when tokenization fails; the cell keeps its
                // plain text, which is what it is already showing.
                .catch(() => undefined);
        });
    }
}

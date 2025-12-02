import { Component, ChangeDetectionStrategy, ViewEncapsulation } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';
import { CommonModule } from '@angular/common';

@Component({
    selector: 'app-expression-renderer',
    standalone: true,
    imports: [CommonModule],
    template: `<div class="expression-renderer" [innerHTML]="highlightedValue"></div>`,
    styleUrls: ['./expression-renderer.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExpressionRendererComponent implements ICellRendererAngularComp {
    public highlightedValue: string = '';

    agInit(params: ICellRendererParams): void {
        this.updateValue(params.value);
    }

    refresh(params: ICellRendererParams): boolean {
        this.updateValue(params.value);
        return true;
    }

    private updateValue(value: string): void {
        if (!value) {
            this.highlightedValue = '';
            return;
        }

        // Escape HTML
        let escaped = value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');

        // Highlight variables (state.x.y)
        escaped = escaped.replace(/(@?state(?:\.[\w$]+)+)\b/g, '<span class="variable">$1</span>');

        // Highlight AND/OR (case insensitive)
        escaped = escaped.replace(/(\b(?:AND|OR|and|or)\b)/g, '<span class="keyword">$1</span>');

        // Handle newlines
        escaped = escaped.replace(/\n/g, '<br>');

        this.highlightedValue = escaped;
    }
}


import { Component, ElementRef, inject } from '@angular/core';
import { ICellEditorParams } from 'ag-grid-community';

import { toDisplayExpression, toStoredExpression } from '../../../../../utils/condition-expression.helper';
import { CDT_COLUMN_KIND, CDT_EXPRESSION_EDITOR_POPUP_WIDTH } from '../../cdt.constants';
import { BaseCellEditor } from '../shared/base-cell-editor';
import { ExpressionBuilderComponent } from './expression-builder.component';

export interface ExpressionBuilderCellEditorParams extends ICellEditorParams {
    variables?: string[] | (() => string[]);
    mode?: 'expression' | 'manipulation';
}

@Component({
    selector: 'app-expression-builder-cell-editor',
    imports: [ExpressionBuilderComponent],
    template: `
        <app-expression-builder
            [value]="initialDisplay"
            [variables]="variables"
            [mode]="mode"
            (valueChange)="onValueChange($event)"
            (commit)="onCommit($event)"
            (cancel)="onCancel()"
        />
    `,
    styles: [
        `
            :host {
                display: block;
                z-index: 10;
                position: relative;
                background: #1f1f23;
                width: 660px;
                min-height: 320px;
            }
        `,
    ],
})
export class ExpressionBuilderCellEditorComponent extends BaseCellEditor<ExpressionBuilderCellEditorParams> {
    initialDisplay = '';
    variables: string[] = [];
    mode: 'expression' | 'manipulation' = CDT_COLUMN_KIND.EXPRESSION;

    private currentDisplay = '';
    private readonly elRef = inject(ElementRef);

    override agInit(params: ExpressionBuilderCellEditorParams): void {
        super.agInit(params);
        this.initialDisplay = toDisplayExpression(params.value ?? '');
        this.currentDisplay = this.initialDisplay;
        this.mode = params.mode ?? CDT_COLUMN_KIND.EXPRESSION;

        const raw = params.variables;
        if (typeof raw === 'function') {
            this.variables = (raw as () => string[])();
        } else if (Array.isArray(raw)) {
            this.variables = raw;
        } else {
            this.variables = [];
        }

        setTimeout(() => this.repositionPopup(params), 0);
    }

    private repositionPopup(params: ExpressionBuilderCellEditorParams): void {
        const cellEl = params.eGridCell as HTMLElement;
        const cellRect = cellEl.getBoundingClientRect();

        let wrapper: HTMLElement | null = this.elRef.nativeElement;
        while (wrapper && !wrapper.classList.contains('ag-popup-editor')) {
            wrapper = wrapper.parentElement;
        }
        if (!wrapper) return;

        const FIXED_WIDTH = CDT_EXPRESSION_EDITOR_POPUP_WIDTH;
        wrapper.style.width = `${FIXED_WIDTH}px`;
        const popupWidth = FIXED_WIDTH;

        const wrapperRect = wrapper.getBoundingClientRect();
        const targetTop = cellRect.top;
        const targetLeft = this.mode === CDT_COLUMN_KIND.MANIPULATION ? cellRect.right - popupWidth : cellRect.left;

        const dx = targetLeft - wrapperRect.left;
        const dy = targetTop - wrapperRect.top;
        wrapper.style.transform = `translate(${dx}px, ${dy}px)`;
    }

    getValue(): string {
        return toStoredExpression(this.currentDisplay);
    }

    getPopupPosition(): 'over' | 'under' {
        return 'over';
    }

    onValueChange(displayValue: string): void {
        this.currentDisplay = displayValue;
    }

    onCommit(displayValue: string): void {
        this.currentDisplay = displayValue;
        this.params.stopEditing();
    }

    onCancel(): void {
        this.params.stopEditing(true);
    }
}

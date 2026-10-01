import { NgTemplateOutlet } from '@angular/common';
import { Component, signal, TemplateRef } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

export interface TemplateCellContext<TRow> {
    $implicit: TRow;
    valueFormatted: string | null | undefined;
}

export interface TemplateCellRendererParams<TRow> extends ICellRendererParams<TRow> {
    template: TemplateRef<TemplateCellContext<TRow>>;
}

/**
 * Renders a cell from an `ng-template` of the grid's own template, so the cell markup keeps the grid's bindings
 * and styles (the template belongs to the grid component) instead of each cell needing its own component.
 */
@Component({
    selector: 'app-template-cell-renderer',
    imports: [NgTemplateOutlet],
    template: `<ng-container *ngTemplateOutlet="template(); context: context()" />`,
})
export class TemplateCellRendererComponent<TRow> implements ICellRendererAngularComp {
    protected readonly template = signal<TemplateRef<TemplateCellContext<TRow>> | null>(null);
    protected readonly context = signal<TemplateCellContext<TRow> | null>(null);

    agInit(params: TemplateCellRendererParams<TRow>): void {
        this.refresh(params);
    }

    refresh(params: TemplateCellRendererParams<TRow>): boolean {
        this.template.set(params.template);
        this.context.set({ $implicit: params.data as TRow, valueFormatted: params.valueFormatted });
        return true;
    }
}

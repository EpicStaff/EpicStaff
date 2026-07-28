import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject } from '@angular/core';
import { IHeaderAngularComp } from 'ag-grid-angular';
import { IHeaderParams } from 'ag-grid-community';

@Component({
    selector: 'app-selection-count-header',
    imports: [CommonModule],
    template: `
        @if (count > 0) {
            <span class="sel-count">({{ count }})</span>
        }
    `,
    styles: [
        `
            :host {
                display: flex;
                align-items: center;
                justify-content: center;
                width: 100%;
                height: 100%;
            }
            .sel-count {
                color: var(--purple-primary);
                font-weight: 500;
                font-size: 13px;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SelectionCountHeaderComponent implements IHeaderAngularComp {
    private cdr = inject(ChangeDetectorRef);
    public count = 0;
    private params!: IHeaderParams;

    agInit(params: IHeaderParams): void {
        this.params = params;
        this.refreshCount();
        params.api.addEventListener('selectionChanged', () => this.refreshCount());
    }

    refresh(): boolean {
        this.refreshCount();
        return true;
    }

    private refreshCount(): void {
        this.count = this.params.api.getSelectedNodes().length;
        this.cdr.markForCheck();
    }
}

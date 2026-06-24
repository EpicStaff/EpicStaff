import { ChangeDetectionStrategy, Component, HostBinding } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';

type DeleteCellRendererParams = ICellRendererParams & {
    isDeletable?: (data: unknown) => boolean;
};

@Component({
    selector: 'app-delete-cell-renderer',
    standalone: true,
    imports: [AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <app-svg-icon
            icon="trash"
            size="1rem"
        />
    `,
    styles: [
        `
            :host {
                height: 100%;
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                color: #b1b1b1;
                transition:
                    color 0.2s,
                    transform 0.2s;
            }
            :host:hover {
                color: #ff7a7a;
                transform: scale(1.1);
            }
            /* Not-completed rows (spare/empty/incomplete agent): looks disabled. */
            :host.disabled {
                color: #4a4a4a;
                opacity: 0.4;
                cursor: default;
            }
            :host.disabled:hover {
                color: #4a4a4a;
                transform: none;
            }
        `,
    ],
})
export class DeleteCellRendererComponent implements ICellRendererAngularComp {
    params!: DeleteCellRendererParams;

    // Disabled (greyed, non-interactive) when the row isn't a completed agent.
    // The click itself is also guarded by the grid's onCellClicked handler.
    @HostBinding('class.disabled') disabled = false;

    agInit(params: DeleteCellRendererParams): void {
        this.params = params;
        this.disabled = !params.isDeletable?.(params.data);
    }

    refresh(params: DeleteCellRendererParams): boolean {
        this.params = params;
        this.disabled = !params.isDeletable?.(params.data);
        return false;
    }
}

import { Component } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { IHeaderParams } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-human-input-header',
    standalone: true,
    imports: [MatTooltipModule, AppSvgIconComponent],
    template: `
        <div
            class="header-container"
            matTooltip="Ask for feedback"
            matTooltipPosition="above"
        >
            <app-svg-icon
                icon="hand-click"
                size="24px"
            />
        </div>
    `,
    styles: [
        `
            :host {
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                padding-right: 3px;
            }
            .header-container {
                display: flex;
                align-items: center;
                justify-content: center;
            }
        `,
    ],
})
export class HumanInputHeaderComponent {
    params!: IHeaderParams;

    agInit(params: IHeaderParams): void {
        this.params = params;
    }

    refresh(params: IHeaderParams): boolean {
        void params;
        return false;
    }
}

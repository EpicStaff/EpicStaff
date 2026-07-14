import { Component, Input } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { StartNodeModel } from '../../../core/models/node.model';

@Component({
    selector: 'app-start-node',
    standalone: true,
    imports: [AppSvgIconComponent],
    template: `
        <div class="start-node">
            <app-svg-icon
                icon="play"
                size="25px"
            ></app-svg-icon>

            <span>Start</span>
        </div>
    `,
    styles: [
        `
            .start-node {
                display: flex;
                align-items: center;
                gap: var(--space-lg);
                font-size: var(--font-size-lg);
                font-weight: var(--font-weight-medium);
                letter-spacing: 0.5px;

                app-svg-icon {
                    color: var(--start-node-icon-color, #000);
                }
            }
        `,
    ],
})
export class StartNodeComponent {
    @Input() node!: StartNodeModel;
}

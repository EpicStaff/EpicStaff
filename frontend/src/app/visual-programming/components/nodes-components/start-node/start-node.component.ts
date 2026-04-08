import { Component, Input } from '@angular/core';

import { StartNodeModel } from '../../../core/models/node.model';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-start-node',
    standalone: true,
    imports: [AppSvgIconComponent],
    template: `
        <div class="start-node">
            <app-svg-icon icon="play" size="25px"></app-svg-icon>

            <span>Start</span>
        </div>
    `,
    styles: [
        `
            .start-node {
                display: flex;
                align-items: center;
                gap: 1rem;
                font-size: 16px;
                font-weight: 500;
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

import { Component, Input } from '@angular/core';

import { StartNodeModel } from '../../../core/models/node.model';

@Component({
    selector: 'app-start-node',
    standalone: true,
    template: `
        <div class="start-node">
            <i class="ti ti-player-play-filled"></i>

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

                i {
                    font-size: 25px;
                    color: var(--start-node-icon-color, #000);
                }
            }
        `,
    ],
})
export class StartNodeComponent {
    @Input() node!: StartNodeModel;
}

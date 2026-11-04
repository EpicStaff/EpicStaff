import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { TooltipOnOverflowDirective } from '@shared/directives';

import { GetGraphLightRequest } from '../../../../features/flows/models/graph.model';
import { subgraphNodeRequest } from '../../../core/helpers/subgraph-flows.util';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';

@Component({
    selector: 'app-flows-menu',
    imports: [MatTooltip, TooltipOnOverflowDirective],
    template: `
        <ul>
            @for (flow of filteredFlows(); track flow.id) {
                <li>
                    <!-- The name has a tooltip only while it is cut short. -->
                    <button
                        type="button"
                        class="menu-item"
                        appTooltipOnOverflow=".flow-name"
                        [matTooltip]="flow.name"
                        matTooltipPosition="right"
                        (click)="onFlowClicked(flow)"
                    >
                        <i
                            class="ti ti-hierarchy-2"
                            aria-hidden="true"
                        ></i>
                        <span class="flow-name">{{ flow.name }}</span>
                    </button>
                </li>
            }
        </ul>
    `,
    styles: [
        `
            ul {
                list-style: none;
                padding: 0 16px;
                margin: 0;
            }
            .menu-item {
                display: flex;
                align-items: center;
                width: 100%;
                padding: 12px 16px;
                border: none;
                border-radius: 8px;
                background: none;
                color: inherit;
                font: inherit;
                text-align: left;
                // The menu list scrolls and clips at its sides: the ring is drawn inside.
                outline-offset: -2px;
                cursor: pointer;
                transition: background 0.2s ease;
                gap: 16px;
                overflow: hidden;
                min-width: 0;
            }
            .menu-item:is(:hover, :focus-visible) {
                background: #2a2a2a;
                color: #fff;
            }
            .menu-item i {
                font-size: 1.125rem;
                color: #00bfa5;
            }

            .flow-name {
                flex: 1;
                overflow: hidden;
                white-space: nowrap;
                text-overflow: ellipsis;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsMenuComponent {
    public readonly flows = input.required<GetGraphLightRequest[]>();
    public readonly searchTerm = input('');
    public readonly nodeSelected = output<CreateNodeRequest>();

    public readonly filteredFlows = computed(() =>
        this.flows().filter((flow) => flow.name.toLowerCase().includes(this.searchTerm().toLowerCase()))
    );

    public onFlowClicked(flow: GetGraphLightRequest): void {
        this.nodeSelected.emit(subgraphNodeRequest(flow));
    }
}

import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { NodeType } from '@shared/models';

import { GetGraphLightRequest } from '../../../../features/flows/models/graph.model';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';

@Component({
    selector: 'app-flows-menu',
    template: `
        <ul>
            @for (flow of filteredFlows(); track flow.id) {
                <li (click)="onFlowClicked(flow)">
                    <i class="ti ti-hierarchy-2"></i>
                    <span class="flow-name">{{ flow.name }}</span>
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
            li {
                display: flex;
                align-items: center;
                padding: 12px 16px;
                border-radius: 8px;
                cursor: pointer;
                transition: background 0.2s ease;
                gap: 16px;
                overflow: hidden;
                min-width: 0;
            }
            li:hover {
                background: #2a2a2a;
                color: #fff;
            }
            li i {
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
        const lightData: GetGraphLightRequest = {
            id: flow.id,
            uuid: flow.uuid,
            name: flow.name,
            description: flow.description,
            tags: flow.tags || [],
        };
        this.nodeSelected.emit({ type: NodeType.SUBGRAPH, overrides: { data: lightData as never } });
    }
}

import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';

import { GetGraphLightRequest } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { NodeType } from '../../../core/enums/node-type';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';

@Component({
    selector: 'app-flows-menu',
    standalone: true,
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
                padding: 0 var(--space-lg);
                margin: 0;
            }
            li {
                display: flex;
                align-items: center;
                padding: var(--space-md) var(--space-lg);
                border-radius: var(--radius-lg);
                cursor: pointer;
                transition: background 0.2s ease;
                gap: var(--space-lg);
                overflow: hidden;
                min-width: 0;
            }
            li:hover {
                background: var(--graphite-780);
                color: var(--color-text-primary);
            }
            li i {
                font-size: var(--font-size-xl);
                color: var(--teal-500);
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
    public readonly searchTerm = input('');
    public readonly currentFlowId = input<number | null>(null);
    public readonly nodeSelected = output<CreateNodeRequest>();

    private readonly flowsApiService = inject(FlowsApiService);

    public readonly flows = toSignal(this.flowsApiService.getGraphsLight(), {
        initialValue: [] as GetGraphLightRequest[],
    });
    public readonly filteredFlows = computed(() =>
        this.flows()
            .filter((flow) => flow.id !== this.currentFlowId())
            .filter((flow) => flow.name.toLowerCase().includes(this.searchTerm().toLowerCase()))
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

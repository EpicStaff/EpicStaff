import { Component, computed, input, linkedSignal, output, signal } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { NodeModel } from '../../core/models/node.model';

@Component({
    selector: 'app-unused-nodes-bar',
    templateUrl: './unused-nodes-bar.component.html',
    styleUrls: ['./unused-nodes-bar.component.scss'],
    imports: [AppSvgIconComponent],
})
export class UnusedNodesBarComponent {
    /** The unused nodes, in the order the arrows step through them. */
    readonly nodes = input.required<NodeModel[]>();
    readonly nodeFocus = output<NodeModel>();

    /**
     * The ids that were unused when the bar was closed, or null while it shows.
     * A node outside them brings the bar back for good.
     */
    private readonly dismissedIds = linkedSignal<NodeModel[], ReadonlySet<string> | null>({
        source: this.nodes,
        computation: (nodes, previous) => {
            const dismissed = previous?.value ?? null;
            return dismissed && nodes.every((node) => dismissed.has(node.id)) ? dismissed : null;
        },
    });
    private readonly currentNodeId = signal<string | null>(null);

    protected readonly isVisible = computed(() => this.dismissedIds() === null);
    private readonly currentPosition = computed(() =>
        this.nodes().findIndex((node) => node.id === this.currentNodeId())
    );
    protected readonly counter = computed(() => {
        const position = this.currentPosition();
        return `${position === -1 ? '–' : position + 1} / ${this.nodes().length}`;
    });

    protected showNext(): void {
        this.showAt(this.currentPosition() + 1);
    }

    protected showPrevious(): void {
        const position = this.currentPosition();
        this.showAt(position <= 0 ? this.nodes().length - 1 : position - 1);
    }

    protected close(): void {
        this.dismissedIds.set(new Set(this.nodes().map((node) => node.id)));
    }

    private showAt(position: number): void {
        const nodes = this.nodes();
        const node = nodes[position % nodes.length];
        this.currentNodeId.set(node.id);
        this.nodeFocus.emit(node);
    }
}

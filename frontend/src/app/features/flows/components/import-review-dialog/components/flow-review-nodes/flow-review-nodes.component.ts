import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { FlowNodeListComponent } from '@shared/components';

import { NodeType } from '../../../../../../visual-programming/core/enums/node-type';
import { FlowReviewNode } from '../../model/review-entry.model';
import { ReviewSessionStore } from '../../review-session.store';
import { ReviewStatusBadgeComponent } from '../review-status-badge/review-status-badge.component';

@Component({
    selector: 'app-flow-review-nodes',
    imports: [FlowNodeListComponent, ReviewStatusBadgeComponent],
    templateUrl: './flow-review-nodes.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowReviewNodesComponent {
    protected readonly store = inject(ReviewSessionStore);

    public readonly nodes = input.required<FlowReviewNode[]>();
    public readonly expanded = input<boolean>(false);
    public readonly nodeTypeLabels = input.required<Partial<Record<NodeType, string>>>();

    public onRowClick(node: FlowReviewNode): void {
        this.store.onFlowNodeRowClick(node);
    }

    public notReviewedLabel(node: FlowReviewNode): string {
        if (this.store.nodeReviewedFieldCount(node) > 0) {
            return `${this.store.nodeRemainingFieldCount(node)} of ${node.codeFieldCount} left`;
        }
        return 'Needs review';
    }
}

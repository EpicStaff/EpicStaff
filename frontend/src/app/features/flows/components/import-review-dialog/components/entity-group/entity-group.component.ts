import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';

import { EntityTypeResult, ImportResultItem } from '../../../../../../core/models/import-result.model';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { NodeType } from '../../../../../../visual-programming/core/enums/node-type';
import { ENTITY_DISPLAY_FIELDS } from '../../constants/import-review.constants';
import { ReviewSessionStore } from '../../review-session.store';
import { getEntityTypeLabel, getGroupIconColor } from '../../utils/entity-icon.util';
import { EntityFieldEntry, EntityFieldsListComponent } from '../entity-fields-list/entity-fields-list.component';
import { EntityIconComponent } from '../entity-icon/entity-icon.component';
import { FlowReviewNodesComponent } from '../flow-review-nodes/flow-review-nodes.component';
import { ReviewStatusBadgeComponent } from '../review-status-badge/review-status-badge.component';

type ItemStatus = 'created' | 'reused';

@Component({
    selector: 'app-entity-group',
    imports: [
        NgTemplateOutlet,
        AppSvgIconComponent,
        EntityIconComponent,
        ReviewStatusBadgeComponent,
        FlowReviewNodesComponent,
        EntityFieldsListComponent,
    ],
    templateUrl: './entity-group.component.html',
    styleUrls: ['./entity-group.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EntityGroupComponent {
    protected readonly store = inject(ReviewSessionStore);

    public readonly entityType = input.required<string>();
    public readonly result = input.required<EntityTypeResult>();
    public readonly isSingleGroup = input<boolean>(false);
    public readonly highlighted = input<boolean>(false);
    public readonly nodeTypeLabels = input.required<Partial<Record<NodeType, string>>>();

    protected readonly getEntityTypeLabel = getEntityTypeLabel;
    protected readonly getGroupIconColor = getGroupIconColor;

    private readonly expandedItems = signal<Set<string>>(new Set());

    public isRowExpandable(item: ImportResultItem): boolean {
        if (this.entityType() !== 'Flow') return false;
        return this.store.hasReviewNodes(item.name) || this.hasExpandableFields(item);
    }

    public isRowClickable(item: ImportResultItem): boolean {
        return this.isRowExpandable(item) || this.store.hasPythonCode(item.name) || this.store.isMcpTool(item.name);
    }

    public onRowClick(item: ImportResultItem, status: ItemStatus): void {
        if (this.isRowExpandable(item)) {
            this.toggleItem(status, item.id);
            return;
        }
        if (this.store.hasPythonCode(item.name) || this.store.isMcpTool(item.name)) {
            this.store.goToToolCode(item.name);
        }
    }

    private itemKey(status: ItemStatus, id: number | string): string {
        return `${status}__${id}`;
    }

    public toggleItem(status: ItemStatus, id: number | string): void {
        const key = this.itemKey(status, id);
        const next = new Set(this.expandedItems());
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        this.expandedItems.set(next);
    }

    public isItemExpanded(status: ItemStatus, id: number | string): boolean {
        return this.expandedItems().has(this.itemKey(status, id));
    }

    public getEntityFields(item: ImportResultItem): EntityFieldEntry[] {
        const config = ENTITY_DISPLAY_FIELDS[this.entityType()] ?? [];
        return config
            .map(({ field, label }) => {
                const val = (item as unknown as Record<string, unknown>)[field];
                if (val === null || val === undefined || val === '') return null;
                const value = typeof val === 'boolean' ? (val ? 'Yes' : 'No') : String(val);
                return { label, value };
            })
            .filter((e): e is EntityFieldEntry => e !== null);
    }

    public hasExpandableFields(item: ImportResultItem): boolean {
        return this.getEntityFields(item).length > 0;
    }

    public toolTransport(item: ImportResultItem): string | null {
        const val = (item as unknown as Record<string, unknown>)['transport'];
        return typeof val === 'string' && val ? val : null;
    }
}

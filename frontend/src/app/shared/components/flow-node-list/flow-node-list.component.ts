import { animate, state, style, transition, trigger } from '@angular/animations';
import { NgClass, NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    input,
    output,
    signal,
    TemplateRef,
} from '@angular/core';

import { NODE_COLORS, NODE_ICONS } from '../../../visual-programming/core/enums/node-config';
import { NodeType } from '../../../visual-programming/core/enums/node-type';
import { SearchComponent } from '../search/search.component';
import { SelectComponent, SelectItem } from '../select/select.component';

export interface FlowNodeListItem {
    name: string;
    nodeType: NodeType;
}

@Component({
    selector: 'app-flow-node-list',
    imports: [NgClass, NgTemplateOutlet, SearchComponent, SelectComponent],
    templateUrl: './flow-node-list.component.html',
    styleUrls: ['./flow-node-list.component.scss'],
    animations: [
        trigger('collapseExpand', [
            state('expanded', style({ height: '*', opacity: 1, overflow: 'hidden' })),
            state('collapsed', style({ height: '0', opacity: 0, overflow: 'hidden' })),
            transition('expanded <=> collapsed', animate('200ms ease')),
        ]),
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowNodeListComponent<T extends FlowNodeListItem = FlowNodeListItem> {
    public readonly nodes = input.required<T[]>();
    public readonly expanded = input<boolean>(false);
    public readonly nodeTypeLabels = input.required<Partial<Record<NodeType, string>>>();
    public readonly trailingTemplate = input<TemplateRef<{ $implicit: T }> | null>(null);
    public readonly searchPlaceholder = input<string>('Search node...');

    public readonly rowClick = output<T>();

    public readonly searchTerm = signal('');
    public readonly nodeTypeFilter = signal<NodeType | null>(null);

    public readonly nodeTypeFilterItems = computed<SelectItem<NodeType | null>[]>(() => {
        const labels = this.nodeTypeLabels();
        const present = new Set(this.nodes().map((node) => node.nodeType));
        const items: SelectItem<NodeType | null>[] = [{ name: 'All', value: null }];
        for (const type of present) {
            items.push({ name: labels[type] ?? type, value: type });
        }
        return items;
    });

    public readonly filteredNodes = computed<T[]>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        const typeFilter = this.nodeTypeFilter();
        return this.nodes().filter((node) => {
            const matchesTerm = !term || node.name.toLowerCase().includes(term);
            const matchesType = typeFilter === null || node.nodeType === typeFilter;
            return matchesTerm && matchesType;
        });
    });

    constructor() {
        effect(() => {
            if (this.expanded()) {
                this.searchTerm.set('');
                this.nodeTypeFilter.set(null);
            }
        });
    }

    public onNodeTypeFilterChange(value: unknown): void {
        this.nodeTypeFilter.set(value as NodeType | null);
    }

    public nodeIcon(nodeType: NodeType): string {
        return NODE_ICONS[nodeType];
    }

    public nodeColor(nodeType: NodeType): string {
        return NODE_COLORS[nodeType];
    }

    public nodeTypeLabel(nodeType: NodeType): string {
        return this.nodeTypeLabels()[nodeType] ?? nodeType;
    }
}

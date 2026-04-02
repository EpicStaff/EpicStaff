import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    EventEmitter,
    Input,
    OnInit,
    Output,
    signal,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FFlowModule } from '@foblex/flow';

import { NODE_COLORS, NODE_ICONS } from '../../core/enums/node-config';
import { NodeType } from '../../core/enums/node-type';
import { AgentNodeModel, LLMNodeModel, NodeModel } from '../../core/models/node.model';
import { NodeItemComponent } from './node-item/node-item.component';

@Component({
    selector: 'app-flow-nodes-panel',
    templateUrl: './flow-nodes-panel.component.html',
    styleUrls: ['./flow-nodes-panel.component.scss'],
    standalone: true,
    imports: [CommonModule, FormsModule, NodeItemComponent, FFlowModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowNodePanelComponent implements OnInit {
    @ViewChild('searchInputRef') searchInputRef!: ElementRef<HTMLInputElement>;

    @Input() set nodeModels(value: NodeModel[]) {
        this.nodes.set(value || []);
    }

    @Output() nodeSelected = new EventEmitter<NodeModel>();

    public isExpanded = signal<boolean>(false);
    public searchQuery = signal<string>('');
    public nodes = signal<NodeModel[]>([]);

    private readonly nodeColors = NODE_COLORS;
    private readonly nodeIcons = NODE_ICONS;

    public filteredNodes = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        if (!query) {
            return this.nodes();
        }

        return this.nodes().filter((node) => this.nodeMatchesSearch(node, query));
    });

    private nodeMatchesSearch(node: NodeModel, query: string): boolean {
        // Always check node_name
        if (node.node_name.toLowerCase().includes(query)) {
            return true;
        }

        // Check specific data properties based on node type
        switch (node.type) {
            case NodeType.START:
                return false; // No additional searchable fields
            case NodeType.AGENT:
                return (node as AgentNodeModel).data?.role?.toLowerCase().includes(query) || false;
            case NodeType.PROJECT:
            case NodeType.TASK:
            case NodeType.PYTHON:
            case NodeType.TOOL:
            case NodeType.TABLE:
                return (
                    (node as NodeModel & { data: { name?: string } }).data?.name?.toLowerCase().includes(query) || false
                );
            case NodeType.LLM:
                return (node as LLMNodeModel).data?.custom_name?.toLowerCase().includes(query) || false;
            default:
                return false;
        }
    }

    constructor() {}

    public ngOnInit(): void {
        // Initialization logic if needed
    }

    public togglePanel(): void {
        const wasExpanded = this.isExpanded();
        this.isExpanded.update((value) => !value);

        // If we're expanding the panel, focus the search input after a short delay
        if (!wasExpanded) {
            setTimeout(() => {
                if (this.searchInputRef?.nativeElement) {
                    this.searchInputRef.nativeElement.focus();
                }
            }, 0);
        }
    }

    public clearSearch(): void {
        this.searchQuery.set('');
        // Focus back on the search input after clearing
        if (this.searchInputRef?.nativeElement) {
            this.searchInputRef.nativeElement.focus();
        }
    }

    public updateSearchQuery(event: Event): void {
        const value = (event.target as HTMLInputElement).value;
        this.searchQuery.set(value);
    }

    public onNodeItemClick(node: NodeModel): void {
        // Emit the selected node to the parent component
        this.nodeSelected.emit(node);
    }
}

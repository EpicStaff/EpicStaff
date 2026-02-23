import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnInit,
  Output,
  EventEmitter,
  ChangeDetectorRef,
  inject,
} from '@angular/core';
import { CommonModule, NgFor } from '@angular/common';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { GraphDto, GetGraphLightRequest } from '../../../../features/flows/models/graph.model';
import { NodeType } from '../../../core/enums/node-type';

@Component({
  selector: 'app-flows-menu',
  imports: [CommonModule, NgFor],
  standalone: true,
  template: `
    <ul>
      <li
        *ngFor="let flow of filteredFlows"
        (click)="onFlowClicked(flow)"
      >
        <i class="ti ti-hierarchy-2"></i>
        <span class="flow-name">{{ flow.name }}</span>
      </li>
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
      }
      li:hover {
        background: #2a2a2a;
        color: #fff;
      }
      li i {
        font-size: 18px;
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
export class FlowsMenuComponent implements OnInit {
  private flowsApiService = inject(FlowsApiService);
  private cdr = inject(ChangeDetectorRef);

  @Input() public searchTerm: string = '';
  @Input() public currentFlowId: number | null = null;
  @Output() public nodeSelected = new EventEmitter<{
    type: NodeType;
    data: GetGraphLightRequest;
  }>();

  public flows: GraphDto[] = [];

  ngOnInit(): void {
    this.flowsApiService.getGraphsLight().subscribe({
      next: (flows: any[]) => {
        this.flows = flows;
        this.cdr.markForCheck();
      },
      error: (err) => console.error('Error fetching flows:', err),
    });
  }

  public get filteredFlows(): GraphDto[] {
    return this.flows
      .filter((flow) => flow.id !== this.currentFlowId)
      .filter((flow) =>
        flow.name.toLowerCase().includes(this.searchTerm.toLowerCase())
      );
  }

  public onFlowClicked(flow: GraphDto): void {
    const lightData: GetGraphLightRequest = {
      id: flow.id,
      name: flow.name,
      description: flow.description,
      tags: flow.tags || [],
    };
    this.nodeSelected.emit({ type: NodeType.SUBGRAPH, data: lightData });
  }
}


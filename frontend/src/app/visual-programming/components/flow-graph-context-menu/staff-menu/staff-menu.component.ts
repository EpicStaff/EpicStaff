import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { AgentsService } from '../../../../services/staff.service';
import { GetAgentRequest } from '../../../../shared/models/agent.model';
import { NodeType } from '../../../core/enums/node-type';

@Component({
  selector: 'app-staff-menu',
  standalone: true,
  imports: [CommonModule],
  template: `
    <ul>
      <li
        *ngFor="let agent of filteredAgents; trackBy: trackByAgentId"
        (click)="onAgentClicked(agent)"
      >
        <i class="ti ti-robot"></i>
        <span class="agent-role">{{ agent.role }}</span>
        <i class="ti ti-plus plus-icon"></i>
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
        justify-content: space-between;
        padding: 12px 16px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.2s ease;
        position: relative;
        gap: 16px;
        overflow: hidden;
      }
      li:hover {
        background: #2a2a2a;
        color: #fff;
      }
      li i {
        font-size: 18px;
        color: #8e5cd9;
      }

      .agent-role {
        flex: 1;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
      }
      .plus-icon {
        font-size: 18px;
        color: #bbb;
        opacity: 0;
        transition: opacity 0.2s ease, color 0.2s ease;
      }
      li:hover .plus-icon {
        opacity: 1;
        color: #fff;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StaffMenuComponent implements OnInit {
  @Input() public searchTerm: string = '';
  @Output() public nodeSelected = new EventEmitter<{
    type: NodeType.AGENT;
    data: GetAgentRequest;
  }>();

  public agents: GetAgentRequest[] = [];

  constructor(
    private agentsService: AgentsService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.agentsService.getAgents().subscribe({
      next: (agents: GetAgentRequest[]) => {
        console.log('Agents:', agents);
        this.agents = agents;
        this.cdr.markForCheck();
      },
      error: (err) => console.error('Error fetching agents:', err),
    });
  }

  public get filteredAgents(): GetAgentRequest[] {
    return this.agents.filter((agent: GetAgentRequest) =>
      agent.role.toLowerCase().includes(this.searchTerm.toLowerCase())
    );
  }

  public onAgentClicked(agent: GetAgentRequest): void {
    console.log('Agent clicked:', agent);
    this.nodeSelected.emit({ type: NodeType.AGENT, data: agent });
  }

  public trackByAgentId(index: number, agent: GetAgentRequest): number {
    return agent.id;
  }
}

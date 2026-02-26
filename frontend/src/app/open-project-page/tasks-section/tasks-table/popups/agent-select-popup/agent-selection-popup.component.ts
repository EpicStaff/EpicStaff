import {
  Component,
  OnInit,
  OnChanges,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  SimpleChanges,
  ViewChild,
  ElementRef,
  OnDestroy,
  AfterViewInit,
} from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { FullAgent } from '../../../../../features/staff/services/full-agent.service';

@Component({
  selector: 'app-agent-selection-popup',
  standalone: true,
  imports: [NgFor, FormsModule, NgIf],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './agent-popup.component.html',
  styleUrls: ['./agent-popup.component.scss'],
})
export class AgentSelectionPopupComponent
  implements OnInit, OnChanges, OnDestroy, AfterViewInit
{
  searchTerm: string = '';

  @Input() agents: FullAgent[] = [];
  @Input() selectedAgent: FullAgent | null = null;
  @Output() agentSelected = new EventEmitter<FullAgent | null>();

  selectedAgentId: number | string | null = null;

  @ViewChild('searchInput') searchInput: ElementRef<HTMLInputElement> | null =
    null;

  private readonly _destroyed$ = new Subject<void>();

  constructor(private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    if (this.selectedAgent) {
      this.selectedAgentId = this.selectedAgent.id;
      console.log(this.selectedAgentId);
    }
  }

  ngAfterViewInit(): void {
    // Focus search input after view is initialized
    setTimeout(() => {
      if (this.searchInput) {
        this.searchInput.nativeElement.focus();
      }
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['selectedAgent'] && changes['selectedAgent'].currentValue) {
      this.selectedAgentId = changes['selectedAgent'].currentValue.id;
    }
  }

  ngOnDestroy(): void {
    this._destroyed$.next();
    this._destroyed$.complete();
  }

  get filteredAgents(): FullAgent[] {
    if (!this.searchTerm) {
      return this.agents;
    }

    const term = this.searchTerm.toLowerCase();
    return this.agents.filter(
      (agent) =>
        agent.role.toLowerCase().includes(term) ||
        (agent.goal && agent.goal.toLowerCase().includes(term)) ||
        (agent.backstory && agent.backstory.toLowerCase().includes(term))
    );
  }

  onSelect(agent: FullAgent): void {
    // If the agent is already selected, deselect it and emit null
    if (this.selectedAgentId === agent.id) {
      this.selectedAgentId = null;
      this.agentSelected.emit(null);
    } else {
      // Otherwise, select the agent and emit it
      this.selectedAgentId = agent.id;
      this.agentSelected.emit(agent);
    }
    this.cdr.markForCheck();
  }
}

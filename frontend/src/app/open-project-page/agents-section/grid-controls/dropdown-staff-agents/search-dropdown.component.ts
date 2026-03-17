import {
  Component,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Input,
  HostBinding,
  OnChanges,
  SimpleChanges,
  Output, 
  EventEmitter,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription, combineLatest } from 'rxjs';

import {
  FullAgent,
  FullAgentService,
} from '../../../../features/staff/services/full-agent.service';
import { StaffAgentCardComponent } from './staff-agent-card/staff-agent-card.component';
import { ProjectStateService } from '../../../services/project-state.service';

@Component({
  selector: 'app-search-dropdown',
  standalone: true,
  imports: [CommonModule, FormsModule, StaffAgentCardComponent],
  templateUrl: './search-dropdown.component.html',
  styleUrls: ['./search-dropdown.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SearchDropdownComponent implements OnInit, OnChanges, OnDestroy {
  @HostBinding('attr.size')
  @Input()
  public currentSize: 'small' | 'medium' | 'large' = 'small';

  @Input() searchTerm: string = '';
  @Output() staffAgentAdded = new EventEmitter<FullAgent>();

  public staffAgents: FullAgent[] = [];
  public filteredStaffAgents: FullAgent[] = [];

  private subscription!: Subscription;

  public isLoading: boolean = true;

  constructor(
    private fullAgentService: FullAgentService,
    private cdr: ChangeDetectorRef,
    private projectStateService: ProjectStateService
  ) {}

  ngOnInit(): void {
    this.loadStaffAgents();
  }

  ngOnChanges(changes: SimpleChanges): void {
    // When searchTerm changes, filter the agents
    if (changes['searchTerm'] && !changes['searchTerm'].firstChange) {
      this.filterStaffAgents();
    }
  }

  private loadStaffAgents(): void {
    // Set loading state to true when starting to load
    this.isLoading = true;
    this.cdr.markForCheck();

    // Combine the full staff agents stream with the project agents stream.
    this.subscription = combineLatest([
      this.fullAgentService.getFullAgents(), // Full list of staff agents
      this.projectStateService.agents$, // Project agents (already assigned)
    ]).subscribe({
      next: ([fullStaffAgents, projectAgents]) => {
        // Filter out staff agents already in the project.
        this.staffAgents = fullStaffAgents.filter(
          (staffAgent) =>
            !projectAgents.some(
              (projectAgent) => projectAgent.id === staffAgent.id
            )
        );

        // Initialize filtered staff agents
        this.filterStaffAgents();

        // Set loading to false after data is loaded
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: (error) => {
        console.error('Error loading staff agents:', error);
        // Also set loading to false on error
        this.isLoading = false;
        this.cdr.markForCheck();
      },
    });
  }

  private filterStaffAgents(): void {
    if (!this.searchTerm || this.searchTerm.trim() === '') {
      // If no search term, show all agents
      this.filteredStaffAgents = [...this.staffAgents];
    } else {
      const searchTermLower = this.searchTerm.toLowerCase().trim();

      // Filter agents based on name, role, or any other relevant properties
      this.filteredStaffAgents = this.staffAgents.filter((agent) => {
        // Adjust these properties based on your FullAgent model structure
        return (
          agent.goal?.toLowerCase().includes(searchTermLower) ||
          agent.role?.toLowerCase().includes(searchTermLower) ||
          agent.backstory?.toLowerCase().includes(searchTermLower)
        );
      });
    }

    this.cdr.markForCheck();
  }

  public onAddStaffAgent(staffAgent: FullAgent): void {
    this.staffAgentAdded.emit(staffAgent);
  }

  public trackStaffAgentById(
    index: number,
    staffAgent: FullAgent
  ): string | number {
    return staffAgent.id;
  }

  ngOnDestroy(): void {
    if (this.subscription) {
      this.subscription.unsubscribe();
    }
  }
}

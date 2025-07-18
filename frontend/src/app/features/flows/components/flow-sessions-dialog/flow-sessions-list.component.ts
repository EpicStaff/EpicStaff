import {
  Component,
  OnInit,
  Inject,
  signal,
  ChangeDetectionStrategy,
  AfterViewInit,
  ViewChild,
  ElementRef,
  effect,
} from '@angular/core';
import { GraphDto } from '../../models/graph.model';
import {
  GraphSession,
  GraphSessionLight,
  GraphSessionService,
  GraphSessionStatus,
} from '../../services/flows-sessions.service';
import { CommonModule } from '@angular/common';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Router } from '@angular/router';
import { CheckboxComponent } from '../../../../shared/components/form-controls/checkbox/checkbox.component';
import { LoadingSpinnerComponent } from '../../../../shared/components/loading-spinner/loading-spinner.component';
import { FlowSessionsTableComponent } from './flow-sessions-table.component';
import { PaginationControlsComponent } from '../../../../shared/components/pagination-controls/pagination-controls.component';
import { FlowSessionStatusFilterDropdownComponent } from './flow-session-status-filter-dropdown.component';

@Component({
  selector: 'app-flow-sessions-list',
  templateUrl: './flow-sessions-list.component.html',
  styleUrls: ['./flow-sessions-list.component.scss'],
  standalone: true,
  imports: [
    CommonModule,
    LoadingSpinnerComponent,
    FlowSessionsTableComponent,
    PaginationControlsComponent,
    FlowSessionStatusFilterDropdownComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowSessionsListComponent implements OnInit {
  public flow!: GraphDto;
  public sessions = signal<GraphSessionLight[]>([]);
  public isLoaded = signal<boolean>(false);
  public currentPage = signal(1);
  public pageSize = signal(10);
  public statusFilter = signal<string[]>(['all']);
  public totalCount = 0;
  private reloadTrigger = signal(0);

  @ViewChild('sessionSearchInput')
  sessionSearchInput!: ElementRef<HTMLInputElement>;

  constructor(
    private graphSessionService: GraphSessionService,
    @Inject(DIALOG_DATA) public data: { flow: GraphDto },
    private router: Router,
    public dialogRef: DialogRef<unknown>
  ) {
    this.flow = data.flow;
    effect(() => {
      const page = this.currentPage();
      const size = this.pageSize();
      const status = this.statusFilter();
      this.reloadTrigger(); // Include this to trigger reload when needed
      this.loadSessions(size, (page - 1) * size, status);
    });
  }

  public ngOnInit(): void {
    this.currentPage.set(1);
  }

  private loadSessions(limit: number, offset: number, status: string[]): void {
    this.isLoaded.set(false);
    if (this.flow && this.flow.id) {
      this.graphSessionService
        .getSessionsByGraphId(this.flow.id, false, limit, offset, status)
        .subscribe({
          next: (sessions) => {
            this.sessions.set(sessions.results);
            this.isLoaded.set(true);
            this.totalCount = sessions.count;
          },
          error: () => {
            this.totalCount = 0;
            this.sessions.set([]);
            this.isLoaded.set(true);
            this.pageSize.set(10);
            this.currentPage.set(1);
          },
        });
    } else {
      this.isLoaded.set(true);
    }
  }

  public onDeleteSelected(ids: number[]): void {
    if (ids.length === 0) return;

    this.graphSessionService.bulkDeleteSessions(ids).subscribe({
      next: () => {
        // Always reload the data to get the correct state from server
        this.reloadAfterDeletion(ids);
        console.log('Sessions deleted successfully', ids);
      },
      error: (err) => {
        console.error('Failed to bulk delete sessions', err);
      },
    });
  }

  private reloadAfterDeletion(deletedIds: number[]): void {
    // Calculate how many sessions would remain on current page
    const currentSessions = this.sessions();
    const remainingSessionsOnPage = currentSessions.filter(
      (session) => !deletedIds.includes(session.id)
    );
    const currentPageNumber = this.currentPage();

    console.log('Reloading after deletion:', {
      deletedIds,
      currentPageNumber,
      remainingOnPage: remainingSessionsOnPage.length,
      totalCount: this.totalCount,
    });

    // If current page becomes empty and we're not on page 1, go to previous page
    if (remainingSessionsOnPage.length === 0 && currentPageNumber > 1) {
      console.log('Page is empty, going to previous page');
      // Go to previous page and let it load
      this.currentPage.set(currentPageNumber - 1);
    } else {
      console.log('Triggering reload via signal');
      // Trigger reload through the signal system
      this.reloadTrigger.update((val) => val + 1);
    }
  }

  public onViewSession(sessionId: number): void {
    // Always use router navigation to ensure route parameter subscriptions fire
    this.router.navigate(['/graph', this.flow.id, 'session', sessionId]);
    this.dialogRef.close();
  }

  public onStopSession(sessionId: number): void {
    this.graphSessionService.stopSessionById(sessionId).subscribe({
      next: (response) => {
        this.sessions.update((sessions) =>
          sessions.map((s) =>
            s.id === sessionId ? { ...s, status: GraphSessionStatus.ENDED } : s
          )
        );
        console.log('Session stopped', sessionId, response);
      },
      error: (err) => {
        console.error('Failed to stop session', err);
      },
    });
  }

  onPageChange(page: number) {
    this.currentPage.set(page);
  }

  onStatusFilterChange(values: string[]) {
    this.statusFilter.set(values);
  }

  public ngOnDestroy() {
    this.sessions.set([]);
  }
}

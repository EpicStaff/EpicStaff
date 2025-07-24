import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit,
  signal,
  inject,
} from '@angular/core';
import {
  GraphDto,
  CreateGraphDtoRequest,
  UpdateGraphDtoRequest,
} from '../../models/graph.model';
import { FlowsApiService } from '../../services/flows-api.service';
import {
  Router,
  RouterOutlet,
  RouterLink,
  RouterLinkActive,
} from '@angular/router';

import { CreateFlowDialogComponent } from '../../components/create-flow-dialog/create-flow-dialog.component';

import { Dialog } from '@angular/cdk/dialog';

import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { TabButtonComponent } from '../../../../shared/components/tab-button/tab-button.component';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import {
  FiltersListComponent,
  SearchFilterChange,
} from '../../../../shared/components/filters-list/filters-list.component';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-flows-list-page',
  standalone: true,
  templateUrl: './flows-list-page.component.html',
  styleUrls: ['./flows-list-page.component.scss'],
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    ButtonComponent,
    TabButtonComponent,
    FormsModule,
    AppIconComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsListPageComponent implements OnDestroy {
  public tabs = [
    { label: 'My Flows', link: 'my' },
    { label: 'Templates', link: 'templates' },
  ];

  public searchTerm: string = '';

  private searchTerms = new Subject<string>();
  private subscription: Subscription;

  private dialog = inject(Dialog);
  private flowStorageService = inject(FlowsStorageService);
  private router = inject(Router);
  private cdr = inject(ChangeDetectorRef);

  constructor() {
    this.subscription = this.searchTerms
      .pipe(debounceTime(300), distinctUntilChanged())
      .subscribe((term) => {
        this.updateSearch(term);
      });
  }

  ngOnDestroy(): void {
    if (this.subscription) {
      this.subscription.unsubscribe();
    }

    this.searchTerm = '';
    this.flowStorageService.setFilter(null);
  }

  public onSearchTermChange(term: string): void {
    this.searchTerms.next(term);
  }

  public clearSearch(): void {
    this.searchTerm = '';
    this.updateSearch('');
  }

  private updateSearch(searchTerm: string): void {
    const filter: SearchFilterChange = {
      searchTerm,
    };
    this.flowStorageService.setFilter(filter);
    this.cdr.markForCheck();
  }

  public openCreateFlowDialog(): void {
    const dialogRef = this.dialog.open<GraphDto | undefined>(
      CreateFlowDialogComponent,
      {
        width: '500px',
      }
    );

    dialogRef.closed.subscribe((result: GraphDto | undefined) => {
      if (result) {
        this.router.navigate(['/flows', result.id]);
      }
    });
  }
}

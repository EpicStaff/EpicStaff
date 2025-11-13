import { Component, ChangeDetectionStrategy, OnDestroy } from '@angular/core';
import {
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    Router,
} from '@angular/router';
// import { SearchComponent } from '../../../../shared/components/search/search.component'; // Likely unused now
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { TabButtonComponent } from '../../../../shared/components/tab-button/tab-button.component';
// import { ButtonVariant } from '../../../../core/enums/button-variants.enum'; // Likely unused now
// import { NgClass } from '@angular/common'; // Likely unused now
import { Dialog } from '@angular/cdk/dialog';
import { CreateProjectComponent } from '../../components/create-project-form-dialog/create-project.component';
import { ProjectsStorageService } from '../../services/projects-storage.service';
import { GetProjectRequest } from '../../models/project.model';
import { SearchFilterChange } from '../../../../shared/components/filters-list/filters-list.component';

import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';
import { FormsModule } from '@angular/forms';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';

@Component({
    selector: 'app-projects-list-page',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './projects-list-page.component.html',
    styleUrls: ['./projects-list-page.component.scss'],
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        ButtonComponent,
        TabButtonComponent,

        FormsModule,
        AppIconComponent,
    ],
})
export class ProjectsListPageComponent implements OnDestroy {
    public tabs = [
        { label: 'My projects', link: 'my' },
        { label: 'Templates', link: 'templates' },
    ];

    public searchTerm: string = '';

    private searchTerms = new Subject<string>();
    private subscription: Subscription;

    constructor(
        public router: Router,
        private dialog: Dialog,
        private projectsService: ProjectsStorageService
    ) {
        this.subscription = this.searchTerms
            .pipe(debounceTime(300), distinctUntilChanged())
            .subscribe((term) => {
                this.updateFilter(term);
            });
    }

    ngOnDestroy(): void {
        if (this.subscription) {
            this.subscription.unsubscribe();
        }

        // Reset search filter when component is destroyed
        this.searchTerm = '';
        this.projectsService.setFilter(null);
    }

    get isMyProjectsActive(): boolean {
        return this.router.url.includes('/projects/my');
    }
    get isTemplatesActive(): boolean {
        return this.router.url.includes('/projects/templates');
    }

    public onSearchTermChange(term: string): void {
        this.searchTerms.next(term);
    }

    public clearSearch(): void {
        this.searchTerm = '';
        this.updateFilter('');
    }

    private updateFilter(searchTerm: string): void {
        const filter = {
            searchTerm,
            selectedTagIds:
                this.projectsService.getCurrentFilter()?.selectedTagIds || [],
        };
        this.projectsService.setFilter(filter);
    }

    // public onProjectTagsChange(event: ProjectTagsFilterChange): void {
    //     const filter = {
    //         searchTerm: this.searchTerm,
    //         selectedTagIds: event.selectedTagIds,
    //     };
    //     this.projectsService.setFilter(filter);
    // }

    public openCreateProjectDialog(): void {
        const dialogRef = this.dialog.open<GetProjectRequest | undefined>(
            CreateProjectComponent,
            {
                maxWidth: '95vw',
                maxHeight: '90vh',
                autoFocus: true,
            }
        );
        dialogRef.closed.subscribe((result: GetProjectRequest | undefined) => {
            if (result) {
                this.router.navigate(['/projects', result.id]);
            }
        });
    }
}

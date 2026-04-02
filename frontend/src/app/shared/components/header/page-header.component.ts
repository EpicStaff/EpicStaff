import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { ProjectCreateButtonComponent } from './header-components/header-create/header-create-button.component';
import { ProjectFavoriteButtonComponent } from './header-components/header-favorite/header-favorite-button.component';
import { ProjectFilterButtonComponent } from './header-components/header-filter/header-filter-button.component';
import { ProjectSearchComponent } from './header-components/header-search/header-search.component';
import { ProjectSortButtonComponent } from './header-components/header-sort/header-sort-button.component';

@Component({
    selector: 'app-page-header',
    standalone: true,
    imports: [
        CommonModule,
        ProjectSearchComponent,
        ProjectFilterButtonComponent,
        ProjectSortButtonComponent,
        ProjectFavoriteButtonComponent,
        ProjectCreateButtonComponent,
    ],
    template: `
        <div class="header" (document:click)="onDocumentClick()">
            <div class="title-search">
                <div class="title">{{ headerTitle }}</div>
                <span *ngIf="projectCount !== 0" class="projects-page-project-count-badge">({{ projectCount }})</span>
            </div>
            <div class="header-actions">
                <app-project-search
                    *ngIf="showSearch"
                    [searchTerm]="searchTerm"
                    [placeholder]="searchPlaceholder"
                    (searchInput)="onSearchInput($event)"
                ></app-project-search>
                <app-project-filter-button
                    *ngIf="showFilter"
                    (filterEvent)="toggleTagsMenu()"
                ></app-project-filter-button>
                <app-project-sort-button *ngIf="showSort" (sortEvent)="onSort()"></app-project-sort-button>
                <app-project-favorite-button
                    *ngIf="showFavoriteToggle"
                    [active]="showFavorites"
                    (favoriteToggle)="toggleFavorite()"
                ></app-project-favorite-button>
                <app-project-create-button
                    *ngIf="showCreate"
                    [buttonTitle]="createButtonTitle"
                    (createEvent)="openCreateForm()"
                ></app-project-create-button>
            </div>
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
            }

            .header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                height: 5rem;
                width: 100%;
                padding: 0 3rem;
                border-bottom: 1px solid var(--color-divider-subtle);
                .title-search {
                    display: flex;
                    align-items: center;
                    position: relative;

                    .title {
                        font-size: 24px;
                        font-weight: 400;

                        line-height: 1;
                        color: var(--white);
                        padding: 0;
                        margin: 0;
                    }

                    .projects-page-project-count-badge {
                        font-size: 17px;
                        font-weight: 500;

                        line-height: 1;
                        color: var(--accent-color);
                        margin-left: 8px;
                        margin-top: 0.3rem;
                    }
                }

                .header-actions {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }
            }
        `,
    ],
})
export class PageHeaderComponent {
    @Input() headerTitle: string = 'Projects';
    @Input() projectCount: number = 0;
    @Input() searchTerm: string = '';
    @Input() searchPlaceholder: string = 'placeholder';
    @Input() showFavorites: boolean = false;
    @Input() createButtonTitle: string = 'New Project';

    // Controls for showing/hiding header components
    @Input() showSearch: boolean = true;
    @Input() showFilter: boolean = true;
    @Input() showSort: boolean = true;
    @Input() showFavoriteToggle: boolean = true;
    @Input() showCreate: boolean = true;

    @Output() searchInput = new EventEmitter<string>();
    @Output() toggleFavoriteFilter = new EventEmitter<void>();
    @Output() openCreate = new EventEmitter<void>();
    @Output() filterToggle = new EventEmitter<void>();
    @Output() sortToggle = new EventEmitter<void>();

    onSearchInput(value: string): void {
        this.searchInput.emit(value);
    }

    toggleFavorite(): void {
        this.toggleFavoriteFilter.emit();
    }

    openCreateForm(): void {
        this.openCreate.emit();
    }

    toggleTagsMenu(): void {
        this.filterToggle.emit();
    }

    onSort(): void {
        this.sortToggle.emit();
    }

    onDocumentClick(): void {
        // Handle clicks outside to close menus if needed
    }
}

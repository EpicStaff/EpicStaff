import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnInit, Output } from '@angular/core';

import { ButtonComponent } from '../buttons/button/button.component';

export interface SearchFilterChange {
    searchTerm: string;
    selectedTagIds?: number[];
}

@Component({
    selector: 'app-filters-list',
    standalone: true,
    templateUrl: './filters-list.component.html',
    styleUrls: ['./filters-list.component.scss'],
    imports: [ButtonComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FiltersListComponent implements OnInit {
    @Input() public searchPlaceholder: string = 'Search...';
    @Input() public showTags: boolean = true;
    @Input() public initialSearchTerm: string = '';

    public searchTerm: string = '';

    @Output() change = new EventEmitter<SearchFilterChange>();

    ngOnInit(): void {
        if (this.initialSearchTerm) {
            this.searchTerm = this.initialSearchTerm;
            this.emitChange(this.initialSearchTerm);
        }
    }

    public onSearchValueChange(searchTerm: string): void {
        // Only update if searchTerm is actually different
        if (this.searchTerm !== searchTerm) {
            this.searchTerm = searchTerm;
            this.emitChange(searchTerm);
        }
    }

    private emitChange(searchTerm: string): void {
        const filterData: SearchFilterChange = {
            searchTerm,
        };
        this.change.emit(filterData);
    }
}

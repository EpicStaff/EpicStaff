import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { FullAgent } from '../../../features/staff/services/full-agent.service';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { SearchDropdownComponent } from './dropdown-staff-agents/search-dropdown.component';

export type GridSizeOption = 'small' | 'medium' | 'large';

@Component({
    selector: 'app-grid-controls',
    standalone: true,
    imports: [CommonModule, FormsModule, SearchDropdownComponent, AppSvgIconComponent],
    templateUrl: './grid-controls.component.html',
    styleUrls: ['./grid-controls.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GridControlsComponent {
    @Input() currentSize: GridSizeOption = 'small';
    @Output() showDropdownChange = new EventEmitter<boolean>();
    @Output() currentSizeChange = new EventEmitter<GridSizeOption>();
    @Output() filterChange = new EventEmitter<void>();
    @Output() sortChange = new EventEmitter<void>();
    @Output() favoriteToggle = new EventEmitter<void>();
    @Output() staffAgentAdded = new EventEmitter<FullAgent>();

    public showDropdown = false;
    public sizeOptions: GridSizeOption[] = ['small', 'medium', 'large'];
    public searchTerm = '';
    public isFavoriteActive = false;

    constructor(private cdr: ChangeDetectorRef) {}

    public onSearchFocus(): void {
        this.showDropdown = true;
        this.showDropdownChange.emit(this.showDropdown);
        this.cdr.markForCheck();
    }

    public onSizeSliderChange(event: Event): void {
        const inputElement = event.target as HTMLInputElement;
        const index = parseInt(inputElement.value, 10);
        const newSize = this.sizeOptions[index];
        this.currentSize = newSize;
        this.currentSizeChange.emit(newSize);
        this.cdr.markForCheck();
    }

    public onCloseDropdown(): void {
        this.showDropdown = false;
        this.searchTerm = '';
        this.showDropdownChange.emit(this.showDropdown);
        this.cdr.markForCheck();
    }

    public onSearchChange(value: string): void {
        this.searchTerm = value;
        this.cdr.markForCheck();
    }

    public onFilter(): void {
        this.filterChange.emit();
    }

    public onSort(): void {
        this.sortChange.emit();
    }

    public onFavoriteToggle(): void {
        this.isFavoriteActive = !this.isFavoriteActive;
        this.favoriteToggle.emit();
        this.cdr.markForCheck();
    }

    public onStaffAgentAdded(agent: FullAgent): void {
        this.staffAgentAdded.emit(agent);
    }
}

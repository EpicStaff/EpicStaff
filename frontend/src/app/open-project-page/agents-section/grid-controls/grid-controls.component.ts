import {
  Component,
  Input,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Output,
  EventEmitter,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { SearchDropdownComponent } from './dropdown-staff-agents/search-dropdown.component';
import { ProjectFavoriteButtonComponent } from '../../../shared/components/header/header-components/header-favorite/header-favorite-button.component';
import { ProjectFilterButtonComponent } from '../../../shared/components/header/header-components/header-filter/header-filter-button.component';
import { ProjectSortButtonComponent } from '../../../shared/components/header/header-components/header-sort/header-sort-button.component';
import { FullAgent } from '../../../features/staff/services/full-agent.service';

export type GridSizeOption = 'small' | 'medium' | 'large';

@Component({
  selector: 'app-grid-controls',
  standalone: true,
  imports: [CommonModule, FormsModule, SearchDropdownComponent],
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

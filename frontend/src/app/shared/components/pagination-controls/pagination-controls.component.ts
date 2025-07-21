// pagination-controls.component.ts
import { CommonModule } from '@angular/common';
import { Component, Input, Output, EventEmitter, computed } from '@angular/core';

@Component({
  selector: 'app-pagination-controls',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './pagination-controls.component.html',
  styleUrls: ['./pagination-controls.component.scss'],
})
export class PaginationControlsComponent {
  @Input() pageSize = 10;
  @Input() totalCount = 0;
  @Input() maxPagesToShow = 5;

  /** ← THIS is your “controlled” page index */
  @Input() currentPage = 1;

  @Output() pageChange = new EventEmitter<number>();

  /** purely derived, no side effects */
  get totalPages() {
    return Math.max(1, Math.ceil(this.totalCount / this.pageSize));
  }

  get pages(): (number | '…')[] {
    const tp = this.totalPages;
    const cp = this.currentPage;
    const max = this.maxPagesToShow;

    // small set → show all
    if (tp <= max) {
      return Array.from({ length: tp }, (_, i) => i + 1);
    }

    const half = Math.floor(max / 2);
    let start = cp - half;
    let end = cp + half;

    // clamp window so it never goes below 2 or above tp-1
    start = Math.max(2, start);
    end = Math.min(tp - 1, end);

    // if we’re too far left, shift window right
    if (cp - half < 2) {
      start = 2;
      end = 1 + max;
    }
    // if we’re too far right, shift window left
    if (cp + half > tp - 1) {
      start = tp - max;
      end = tp - 1;
    }

    const pages: (number | '…')[] = [1];
    if (start > 2) pages.push('…');
    for (let i = start; i <= end; i++) pages.push(i);
    if (end < tp - 1) pages.push('…');
    pages.push(tp);

    return pages;
  }

  prev() { if (this.currentPage > 1) this.pageChange.emit(this.currentPage - 1); }
  next() { if (this.currentPage < this.totalPages) this.pageChange.emit(this.currentPage + 1); }
  goTo(pg: number) { if (pg !== this.currentPage) this.pageChange.emit(pg); }
}

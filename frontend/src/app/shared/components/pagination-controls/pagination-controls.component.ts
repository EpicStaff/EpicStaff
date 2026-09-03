// pagination-controls.component.ts
import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

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

        // window of `max` consecutive pages centred on the current one, clamped to
        // [1, tp] — the first and last page count towards it whenever it reaches them
        let start = cp - Math.floor((max - 1) / 2);
        let end = start + max - 1;

        if (start < 1) {
            start = 1;
            end = max;
        }
        if (end > tp) {
            end = tp;
            start = tp - max + 1;
        }

        const pages: (number | '…')[] = [];
        if (start > 1) {
            pages.push(1);
            // a gap of exactly one page shows that page instead of an ellipsis
            if (start === 3) pages.push(2);
            else if (start > 3) pages.push('…');
        }
        for (let i = start; i <= end; i++) pages.push(i);
        if (end < tp) {
            if (end === tp - 2) pages.push(tp - 1);
            else if (end < tp - 2) pages.push('…');
            pages.push(tp);
        }

        return pages;
    }

    prev() {
        if (this.currentPage > 1) this.pageChange.emit(this.currentPage - 1);
    }
    next() {
        if (this.currentPage < this.totalPages) this.pageChange.emit(this.currentPage + 1);
    }
    goTo(pg: number) {
        if (pg !== this.currentPage) this.pageChange.emit(pg);
    }
}

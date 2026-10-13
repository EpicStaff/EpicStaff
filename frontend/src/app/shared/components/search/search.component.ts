import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, ElementRef, input, model, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-search',
    imports: [CommonModule, AppSvgIconComponent, FormsModule, MatTooltipModule],
    templateUrl: './search.component.html',
    styleUrls: ['./search.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SearchComponent {
    width = input<string>('100%');
    mod = input<'default' | 'small'>('default');
    placeholder = input<string>('Search...');
    icon = input<string>('search');
    /** The field's accessible name where no visible label names it; the placeholder is only a hint. */
    ariaLabel = input<string | null>(null);
    searchTerm = model<string>('');

    private readonly inputElement = viewChild.required<ElementRef<HTMLInputElement>>('searchInput');

    onSearchTermChange(value: string): void {
        const trimmedValue = value.trim();

        // Only emit if the value has actually changed
        if (trimmedValue !== this.searchTerm()) {
            this.searchTerm.set(value);
        }
    }

    clearSearch(): void {
        this.searchTerm.set('');
        // The clear button disappears with the text: keep the focus in the field rather than drop it on the page.
        this.inputElement().nativeElement.focus();
    }
}

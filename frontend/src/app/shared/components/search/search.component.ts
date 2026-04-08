import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-search',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, FormsModule],
    templateUrl: './search.component.html',
    styleUrls: ['./search.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SearchComponent {
    width = input<string>('100%');
    mod = input<'default' | 'small'>('default');
    placeholder = input<string>('Search...');
    icon = input<string>('search');
    searchTerm = model<string>('');

    onSearchTermChange(value: string): void {
        const trimmedValue = value.trim();

        // Only emit if the value has actually changed
        if (trimmedValue !== this.searchTerm()) {
            this.searchTerm.set(value);
        }
    }

    clearSearch(): void {
        this.searchTerm.set('');
    }
}

import {
    Component,
    ChangeDetectionStrategy,
    model, input,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import {FormsModule} from "@angular/forms";

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

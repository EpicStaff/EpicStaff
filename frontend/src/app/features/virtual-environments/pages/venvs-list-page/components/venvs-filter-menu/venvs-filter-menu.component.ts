import { ChangeDetectionStrategy, Component, effect, input, output, signal } from '@angular/core';
import { ButtonComponent, CheckboxComponent } from '@shared/components';

/** What the venv list is narrowed by. The search box in the page header is not part of it:
 *  it narrows as you type, while this panel applies on Save. */
export interface VenvsFilterState {
    readonly favoritesOnly: boolean;
}

export const EMPTY_VENVS_FILTER: VenvsFilterState = { favoritesOnly: false };

@Component({
    selector: 'app-venvs-filter-menu',
    imports: [ButtonComponent, CheckboxComponent],
    templateUrl: './venvs-filter-menu.component.html',
    styleUrls: ['./venvs-filter-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VenvsFilterMenuComponent {
    public readonly initial = input.required<VenvsFilterState>();

    public readonly save = output<VenvsFilterState>();
    public readonly cancel = output<void>();
    public readonly clear = output<void>();

    protected readonly draftFavoritesOnly = signal<boolean>(false);

    constructor() {
        // The draft starts from what the page has applied, so reopening the panel shows the
        // filter as it stands rather than as it was left when it was last edited.
        effect(() => this.draftFavoritesOnly.set(this.initial().favoritesOnly));
    }

    protected onToggleFavoritesOnly(): void {
        this.draftFavoritesOnly.update((value) => !value);
    }

    protected onSave(): void {
        this.save.emit({ favoritesOnly: this.draftFavoritesOnly() });
    }

    protected onCancel(): void {
        this.cancel.emit();
    }

    protected onClear(): void {
        this.draftFavoritesOnly.set(EMPTY_VENVS_FILTER.favoritesOnly);
        this.clear.emit();
    }
}

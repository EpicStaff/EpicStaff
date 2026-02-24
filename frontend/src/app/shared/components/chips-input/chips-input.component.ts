import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    input,
    model,
    output,
    signal,
    ViewChild
} from '@angular/core';
import {FormsModule} from "@angular/forms";
import {AppIconComponent, SelectItem} from "@shared/components";

@Component({
    selector: 'app-chips-input',
    templateUrl: './chips-input.component.html',
    styleUrls: ['./chips-input.component.scss'],
    imports: [
        FormsModule,
        AppIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ChipsInputComponent {
    @ViewChild('inputRef') inputRef!: ElementRef<HTMLInputElement>;

    placeholder = input<string>('');
    chips = input<SelectItem[]>([]);

    inputValue = signal('');
    highlightedIndex = signal(0);
    isAutocompleteOpen = signal(false);
    selectedChips = model<SelectItem[]>([]);
    selectionChange = output<unknown[]>();

    filteredChips = computed(() => {
        const val = this.inputValue().toLowerCase();

        return this.chips().filter(chip => {
              return chip.name.toLowerCase().includes(val)
                  && !this.selectedChips().some(s => s.name === chip.name);
            }
        );
    });

    addInput() {
        const option = this.filteredChips()[this.highlightedIndex()];
        if (option) {
            this.select(option);
        }
    }

    remove(event: Event, index: number) {
        event.stopPropagation();

        const updated = [...this.selectedChips()];
        updated.splice(index, 1);
        this.selectedChips.set(updated);
        this.emitChange();
    }

    select(option: SelectItem) {
        if (!this.selectedChips().some(s => s.value === option.value)) {
            this.selectedChips.update(arr => [...arr, option]);
        }
        this.inputValue.set('');
        this.highlightedIndex.set(0);
        this.emitChange();
    }

    private emitChange() {
        const values = this.selectedChips().map(chip => chip.value);
        this.selectionChange.emit(values);
    }

    highlightNext() {
        if (!this.filteredChips().length) return;
        this.highlightedIndex.update(curr => Math.min(curr + 1, this.filteredChips().length - 1));
    }

    highlightPrev() {
        if (!this.filteredChips().length) return;
        this.highlightedIndex.update(curr => Math.max(curr - 1, 0));
    }

    onFocus() {
        this.isAutocompleteOpen.set(true);
    }

    onBlur() {
        this.isAutocompleteOpen.set(false);
    }
}

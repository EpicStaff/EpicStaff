import {
    afterNextRender,
    Component,
    ElementRef,
    forwardRef,
    inject,
    Injector,
    input,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';

import { TooltipComponent } from '../tooltip/tooltip.component';

/** A row as typed; the id keeps each input in place while the rows above it are removed. */
interface StringListRow {
    id: number;
    value: string;
}

/**
 * A list of single values, one input per row: any row can be removed, "Add" appends an empty one. The control's value
 * is the trimmed, non-empty rows; an empty value shows one empty row to type in.
 */
@Component({
    selector: 'app-string-list',
    imports: [TooltipComponent, MatTooltipModule],
    templateUrl: './string-list.component.html',
    styleUrls: ['./string-list.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => StringListComponent),
            multi: true,
        },
    ],
})
export class StringListComponent implements ControlValueAccessor {
    readonly label = input<string>('');
    readonly tooltipText = input<string>('');
    readonly placeholder = input<string>('');
    readonly addButtonText = input<string>('+ Add');
    /** What a row is, in its screen-reader labels: "<rowLabel>, row 1". */
    readonly rowLabel = input<string>('Item');

    private readonly rowInputs = viewChildren<ElementRef<HTMLInputElement>>('rowInput');
    private readonly addButton = viewChild.required<ElementRef<HTMLButtonElement>>('addButton');

    protected readonly rows = signal<StringListRow[]>([]);
    protected readonly isDisabled = signal(false);

    private readonly injector = inject(Injector);
    private nextRowId = 0;
    private onChange: (value: string[]) => void = () => {};
    private onTouched: () => void = () => {};

    writeValue(value: string[] | null): void {
        const values = value?.length ? value : [''];
        this.rows.set(values.map((text) => this.newRow(text)));
    }

    registerOnChange(fn: (value: string[]) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }

    protected updateRow(id: number, value: string): void {
        this.rows.update((rows) => rows.map((row) => (row.id === id ? { ...row, value } : row)));
        this.emit();
    }

    /**
     * Removes the row and, once the list is redrawn, puts the cursor in the row now at its place, else the row above,
     * else on the add button, so keyboard focus is not lost with the removed button.
     */
    protected removeRow(id: number): void {
        const removedIndex = this.rows().findIndex((row) => row.id === id);
        this.rows.update((rows) => rows.filter((row) => row.id !== id));
        this.emit();
        this.onTouched();
        afterNextRender(
            () => {
                const inputs = this.rowInputs();
                const target = inputs[removedIndex] ?? inputs.at(-1) ?? this.addButton();
                target.nativeElement.focus();
            },
            { injector: this.injector }
        );
    }

    /** Appends an empty row and puts the cursor in it once it is drawn. */
    protected addRow(): void {
        this.rows.update((rows) => [...rows, this.newRow('')]);
        afterNextRender(() => this.rowInputs().at(-1)?.nativeElement.focus(), { injector: this.injector });
    }

    protected markTouched(): void {
        this.onTouched();
    }

    protected rowAriaLabel(index: number): string {
        return `${this.rowLabel()}, row ${index + 1}`;
    }

    protected removeAriaLabel(index: number): string {
        return `Remove ${this.rowLabel().toLowerCase()}, row ${index + 1}`;
    }

    private newRow(value: string): StringListRow {
        return { id: this.nextRowId++, value };
    }

    /** Emits the values only: trimmed, without the empty rows. */
    private emit(): void {
        this.onChange(
            this.rows()
                .map((row) => row.value.trim())
                .filter((value) => value !== '')
        );
    }
}

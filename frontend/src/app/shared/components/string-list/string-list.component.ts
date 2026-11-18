import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    forwardRef,
    inject,
    Injector,
    input,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    ControlValueAccessor,
    NG_VALIDATORS,
    NG_VALUE_ACCESSOR,
    TouchedChangeEvent,
    ValidationErrors,
    Validator,
} from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { filter } from 'rxjs';

import { TooltipComponent } from '../tooltip/tooltip.component';

/** A row as typed; the id keeps each input in place while the rows above it are removed. */
interface StringListRow {
    id: number;
    value: string;
    /** Whether the user changed the text since `writeValue` put it there; only then does leaving the row split it. */
    isEdited: boolean;
}

/** Where the caret goes in a row the list moves the focus to. */
type CaretPlace = 'start' | 'end';

let nextListId = 0;

/**
 * A list of single values, one input per row: any row can be removed, "Add" or Enter adds an empty one. The control's
 * value is the trimmed, non-empty rows; an empty value shows one empty row to type in.
 *
 * Optional rules: `splitPattern` turns separated text (pasted, typed or autofilled) into one row per piece;
 * `itemError` words what is wrong with one value; `maxItems` caps the filled rows. Both rules make the control invalid.
 * `itemError` and `maxItems` are read when the value is validated, so a change to them applies from the next edit.
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
        {
            provide: NG_VALIDATORS,
            useExisting: forwardRef(() => StringListComponent),
            multi: true,
        },
    ],
})
export class StringListComponent implements ControlValueAccessor, Validator {
    readonly label = input<string>('');
    readonly tooltipText = input<string>('');
    readonly placeholder = input<string>('');
    readonly addButtonText = input<string>('+ Add');
    /** What a row is, in its screen-reader labels: "<rowLabel>, row 1". */
    readonly rowLabel = input<string>('Item');
    /** What separates values in one text; null keeps any text in its row. It must not match inside a value. */
    readonly splitPattern = input<RegExp | null>(null);
    /** Why one trimmed, non-empty value is invalid, or null when it is valid. */
    readonly itemError = input<((value: string) => string | null) | null>(null);
    /** The most filled rows allowed; null for no cap. */
    readonly maxItems = input<number | null>(null);
    /** Said on the disabled add button at the cap, and under the list above it. */
    readonly maxItemsText = input<string>('');

    private readonly rowInputs = viewChildren<ElementRef<HTMLInputElement>>('rowInput');
    private readonly addButton = viewChild.required<ElementRef<HTMLButtonElement>>('addButton');

    protected readonly rows = signal<StringListRow[]>([]);
    protected readonly isDisabled = signal(false);
    // A row's error shows once it lost focus, or once the control is touched (a save attempt touches it), but never in
    // the row being typed for the first time.
    private readonly blurredRowIds = signal<ReadonlySet<number>>(new Set());
    private readonly focusedRowId = signal<number | null>(null);
    private readonly isControlTouched = signal(false);

    private readonly rowErrors = computed(() => {
        const itemError = this.itemError();
        return this.rows().map((row) => {
            const value = row.value.trim();
            return value && itemError ? itemError(value) : null;
        });
    });
    private readonly filledCount = computed(() => this.rows().filter((row) => row.value.trim() !== '').length);
    protected readonly isAtLimit = computed(() => {
        const max = this.maxItems();
        return max !== null && this.filledCount() >= max;
    });
    protected readonly isOverLimit = computed(() => {
        const max = this.maxItems();
        return max !== null && this.filledCount() > max;
    });
    protected readonly shownRowErrors = computed(() => {
        const blurred = this.blurredRowIds();
        const focused = this.focusedRowId();
        const touched = this.isControlTouched();
        return this.rows().map((row, index) => {
            const isFreshlyTyped = row.id === focused && !blurred.has(row.id);
            const isShown = blurred.has(row.id) || (touched && !isFreshlyTyped);
            return isShown ? this.rowErrors()[index] : null;
        });
    });

    // Unique per list: the error messages' ids, which the rows and the group point at.
    protected readonly idPrefix = `string-list-${nextListId++}`;
    protected readonly limitErrorId = `${this.idPrefix}-limit-error`;

    private readonly injector = inject(Injector);
    private readonly destroyRef = inject(DestroyRef);
    private nextRowId = 0;
    private validatedControl: AbstractControl | null = null;
    private onChange: (value: string[]) => void = () => {};
    private onTouched: () => void = () => {};

    writeValue(value: string[] | null): void {
        const values = value?.length ? value : [''];
        this.rows.set(values.map((text) => this.newRow(text)));
        this.blurredRowIds.set(new Set());
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

    /** Invalid when a value breaks `itemError`, or when there are more values than `maxItems`. */
    validate(control: AbstractControl<string[] | null>): ValidationErrors | null {
        this.followTouched(control);
        const values = control.value ?? [];
        const itemError = this.itemError();
        const max = this.maxItems();
        const errors: ValidationErrors = {};
        if (itemError && values.some((value) => itemError(value) !== null)) errors['stringListItem'] = true;
        if (max !== null && values.length > max) errors['stringListMaxItems'] = { max, actual: values.length };
        return Object.keys(errors).length ? errors : null;
    }

    protected updateRow(id: number, value: string): void {
        this.rows.update((rows) => rows.map((row) => (row.id === id ? { ...row, value, isEdited: true } : row)));
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
        const row = this.newRow('');
        this.rows.update((rows) => [...rows, row]);
        this.focusRow(row.id, 'end');
    }

    /**
     * Enter adds an empty row after this one and moves there; in an empty row (or at the cap) it moves to the next row
     * instead, if any, so Enter never piles up empty rows. It never submits the form around the list.
     */
    protected onEnter(event: Event, id: number): void {
        // Angular types a key-filtered event as a plain Event.
        if (!(event instanceof KeyboardEvent)) return;
        if (event.isComposing || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        const rows = this.rows();
        const index = rows.findIndex((row) => row.id === id);
        if (rows[index].value.trim() === '' || this.isAtLimit()) {
            const next = rows[index + 1];
            if (next) this.focusRow(next.id, 'end');
            return;
        }
        const row = this.newRow('');
        this.rows.update((current) => [...current.slice(0, index + 1), row, ...current.slice(index + 1)]);
        this.focusRow(row.id, 'end');
    }

    /** Pasted text with separators replaces the selection, then goes one piece per row; the cursor ends in the last. */
    protected onPaste(event: ClipboardEvent, id: number, rowInput: HTMLInputElement): void {
        const pasted = event.clipboardData?.getData('text') ?? '';
        if (!this.hasSeparator(pasted)) return;
        event.preventDefault();
        const { before, after } = this.aroundSelection(rowInput);
        const lastId = this.splitRow(id, before + pasted + after);
        this.focusRow(lastId, 'end');
    }

    /**
     * A typed separator ends the row there: the text after it moves to a new row below, where the cursor goes. At the
     * start of a row (or in an empty one) it is dropped. When the text after it only repeats the text before, no row is
     * added. Typed text that is more than separators is split as pasted.
     */
    protected onBeforeInput(event: InputEvent, id: number, rowInput: HTMLInputElement): void {
        const typed = event.data ?? '';
        if (event.inputType !== 'insertText' || !this.hasSeparator(typed)) return;
        event.preventDefault();
        const { before, after } = this.aroundSelection(rowInput);
        if (!this.isOnlySeparators(typed)) {
            this.focusRow(this.splitRow(id, before + typed + after), 'end');
            return;
        }
        if (before.trim() === '') return;
        const index = this.rows().findIndex((row) => row.id === id);
        // `before` is not blank, so it is always the first piece; the second is gone when `after` is blank or repeats it.
        const pieces = this.cleanPieces([before, after]);
        const kept = pieces[0] ?? '';
        const moved: string | undefined = pieces[1];
        if (moved === undefined && after.trim() !== '') {
            this.updateRow(id, kept);
            this.focusRow(id, 'end');
            return;
        }
        const row = this.newRow(moved ?? '');
        this.rows.update((rows) => [
            ...rows.slice(0, index),
            { ...rows[index], value: kept },
            row,
            ...rows.slice(index + 1),
        ]);
        this.emit();
        this.focusRow(row.id, 'start');
    }

    protected onFocus(id: number): void {
        this.focusedRowId.set(id);
    }

    /**
     * Splits what the user left separated (autofill), but never a value `writeValue` put there untouched; shows the
     * row's error from now on and touches the control.
     */
    protected onBlur(id: number): void {
        const row = this.rows().find((current) => current.id === id);
        if (row?.isEdited && this.hasSeparator(row.value)) this.splitRow(id, row.value);
        this.focusedRowId.update((focused) => (focused === id ? null : focused));
        this.blurredRowIds.update((blurred) => new Set(blurred).add(id));
        this.onTouched();
    }

    protected rowAriaLabel(index: number): string {
        return `${this.rowLabel()}, row ${index + 1}`;
    }

    protected removeAriaLabel(index: number): string {
        return `Remove ${this.rowLabel().toLowerCase()}, row ${index + 1}`;
    }

    protected rowErrorId(id: number): string {
        return `${this.idPrefix}-error-${id}`;
    }

    private newRow(value: string): StringListRow {
        return { id: this.nextRowId++, value, isEdited: false };
    }

    /** Emits the values only: trimmed, without the empty rows. */
    private emit(): void {
        this.onChange(
            this.rows()
                .map((row) => row.value.trim())
                .filter((value) => value !== '')
        );
    }

    /**
     * Puts the pieces of the text in this row (the first) and in new rows right after it (the rest), without empty
     * pieces or repeats within the text. Returns the id of the last of these rows.
     */
    private splitRow(id: number, text: string): number {
        const pattern = this.splitPattern();
        const pieces = this.cleanPieces(pattern ? text.split(pattern) : [text]);
        const index = this.rows().findIndex((row) => row.id === id);
        const added = pieces.slice(1).map((piece) => this.newRow(piece));
        this.rows.update((rows) => [
            ...rows.slice(0, index),
            { ...rows[index], value: pieces[0] ?? '' },
            ...added,
            ...rows.slice(index + 1),
        ]);
        this.emit();
        return added.at(-1)?.id ?? id;
    }

    /**
     * The trimmed, non-empty pieces of one split, each once. Only the pieces are compared with each other: a piece that
     * another row already holds stays, so the list never drops text the user typed or kept.
     */
    private cleanPieces(pieces: string[]): string[] {
        const seen = new Set<string>();
        const kept: string[] = [];
        for (const piece of pieces.map((text) => text.trim())) {
            if (piece === '' || seen.has(piece)) continue;
            seen.add(piece);
            kept.push(piece);
        }
        return kept;
    }

    // `split` rather than `test`: a global pattern's `test` keeps state between calls.
    private hasSeparator(text: string): boolean {
        const pattern = this.splitPattern();
        return pattern !== null && text.split(pattern).length > 1;
    }

    private isOnlySeparators(text: string): boolean {
        const pattern = this.splitPattern();
        return pattern !== null && text.split(pattern).every((piece) => piece === '');
    }

    private aroundSelection(rowInput: HTMLInputElement): { before: string; after: string } {
        const value = rowInput.value;
        const start = rowInput.selectionStart ?? value.length;
        const end = rowInput.selectionEnd ?? start;
        return { before: value.slice(0, start), after: value.slice(end) };
    }

    private focusRow(id: number, caret: CaretPlace): void {
        afterNextRender(
            () => {
                const index = this.rows().findIndex((row) => row.id === id);
                const rowInput = this.rowInputs()[index]?.nativeElement;
                if (!rowInput) return;
                rowInput.focus();
                const position = caret === 'start' ? 0 : rowInput.value.length;
                rowInput.setSelectionRange(position, position);
            },
            { injector: this.injector }
        );
    }

    /** Follows the control's touched state, so a save attempt (`markAllAsTouched`) shows the rows' errors. */
    private followTouched(control: AbstractControl): void {
        if (control === this.validatedControl) return;
        this.validatedControl = control;
        this.isControlTouched.set(control.touched);
        control.events
            .pipe(
                filter((event) => event instanceof TouchedChangeEvent),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.isControlTouched.set(control.touched));
    }
}

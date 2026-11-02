import {
    afterNextRender,
    Component,
    computed,
    ElementRef,
    inject,
    Injector,
    input,
    model,
    OnInit,
    output,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';

export interface PickerOption {
    readonly id: string;
    readonly label: string;
}

export interface PickerGroup {
    readonly title: string | null;
    readonly options: readonly PickerOption[];
}

interface ListPlacement {
    readonly opensUp: boolean;
    readonly maxHeight: number;
}

const LIST_MAX_HEIGHT_PX = 200;
const LIST_MIN_HEIGHT_PX = 96;
const LIST_GAP_PX = 4;

interface ShownOption extends PickerOption {
    readonly elementId: string;
}

interface ShownGroup {
    readonly title: string | null;
    readonly titleId: string;
    readonly options: readonly ShownOption[];
}

let nextPickerId = 0;

@Component({
    selector: 'app-shortcut-picker',
    templateUrl: './shortcut-picker.component.html',
    styleUrl: './shortcut-picker.component.scss',
})
export class ShortcutPickerComponent implements OnInit {
    readonly label = input.required<string>();
    readonly placeholder = input('');
    readonly listLabel = input.required<string>();
    readonly emptyText = input.required<string>();
    readonly groups = input.required<readonly PickerGroup[]>();
    readonly startOpen = input(false);
    readonly selected = model<string | null>(null);
    readonly advance = output<void>();

    private readonly pickerInput = viewChild.required<ElementRef<HTMLInputElement>>('pickerInput');
    private readonly optionElements = viewChildren<ElementRef<HTMLElement>>('optionElement');

    protected readonly query = signal('');
    protected readonly isListOpen = signal(false);
    protected readonly activeIndex = signal(0);
    protected readonly listPlacement = signal<ListPlacement>({ opensUp: false, maxHeight: LIST_MAX_HEIGHT_PX });

    protected readonly shownGroups = computed<readonly ShownGroup[]>(() => {
        const selected = this.selected();
        const showAll = selected !== null && this.query() === this.labelOf(selected);
        const term = showAll ? '' : this.query().trim().toLowerCase();
        return this.groups()
            .map((group, index) => ({
                title: group.title,
                titleId: `${this.idPrefix}-group-${index}`,
                options: group.options
                    .filter((option) => option.label.toLowerCase().includes(term))
                    .map((option) => ({ ...option, elementId: `${this.idPrefix}-option-${option.id}` })),
            }))
            .filter((group) => group.options.length > 0);
    });

    protected readonly options = computed(() => this.shownGroups().flatMap((group) => group.options));

    protected readonly activeOption = computed(() => (this.isListOpen() ? this.options()[this.activeIndex()] : null));

    protected readonly idPrefix = `shortcut-picker-${nextPickerId++}`;

    private readonly injector = inject(Injector);
    private selectOnMouseUp = false;

    ngOnInit(): void {
        const selected = this.selected();
        if (selected !== null) {
            this.query.set(this.labelOf(selected));
        } else if (this.startOpen()) {
            this.isListOpen.set(true);
            afterNextRender(() => this.placeList(), { injector: this.injector });
        }
    }

    focus(): void {
        this.pickerInput().nativeElement.focus();
    }

    close(): void {
        this.isListOpen.set(false);
    }

    protected onPointerDown(): void {
        const input = this.pickerInput().nativeElement;
        this.selectOnMouseUp = input.ownerDocument.activeElement !== input;
    }

    protected onMouseUp(event: MouseEvent): void {
        if (this.selectOnMouseUp) {
            this.selectOnMouseUp = false;
            event.preventDefault();
            this.pickerInput().nativeElement.select();
        }
    }

    protected onQueryInput(value: string): void {
        this.query.set(value);
        this.selected.set(null);
        this.activeIndex.set(0);
        if (!this.isListOpen()) {
            this.placeList();
            this.isListOpen.set(true);
        }
    }

    protected openList(): void {
        if (!this.isListOpen()) {
            this.activeIndex.set(this.selectedOptionIndex());
            this.placeList();
            this.isListOpen.set(true);
        }
    }

    protected onKeydown(event: KeyboardEvent): void {
        const lastIndex = this.options().length - 1;
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                if (this.isListOpen()) {
                    this.activeIndex.update((index) => Math.min(index + 1, lastIndex));
                } else {
                    this.openList();
                }
                this.revealActiveOption();
                return;
            case 'ArrowUp':
                event.preventDefault();
                this.activeIndex.update((index) => Math.max(index - 1, 0));
                this.revealActiveOption();
                return;
            case 'Enter': {
                const option = this.activeOption();
                if (option) {
                    event.preventDefault();
                    this.pick(option);
                    this.advance.emit();
                } else if (!this.isListOpen() && this.selected() !== null) {
                    event.preventDefault();
                    this.advance.emit();
                }
                return;
            }
            case 'Escape':
                if (this.isListOpen()) {
                    event.preventDefault();
                    this.isListOpen.set(false);
                }
                return;
        }
    }

    protected pick(option: PickerOption): void {
        this.selected.set(option.id);
        this.query.set(option.label);
        this.isListOpen.set(false);
    }

    private placeList(): void {
        const input = this.pickerInput().nativeElement;
        const boundary = layoutBoundaryOf(input);
        if (boundary === null) {
            this.listPlacement.set({ opensUp: false, maxHeight: LIST_MAX_HEIGHT_PX });
            return;
        }
        const inputRect = input.getBoundingClientRect();
        const roomBelow = boundary.bottom - inputRect.bottom - LIST_GAP_PX;
        const roomAbove = inputRect.top - boundary.top - LIST_GAP_PX;
        const opensUp = roomBelow < LIST_MAX_HEIGHT_PX && roomAbove > roomBelow;
        const room = opensUp ? roomAbove : roomBelow;
        this.listPlacement.set({
            opensUp,
            maxHeight: Math.max(LIST_MIN_HEIGHT_PX, Math.min(LIST_MAX_HEIGHT_PX, room)),
        });
    }

    private labelOf(id: string): string {
        for (const group of this.groups()) {
            const option = group.options.find((candidate) => candidate.id === id);
            if (option) {
                return option.label;
            }
        }
        return '';
    }

    private selectedOptionIndex(): number {
        const selected = this.selected();
        return Math.max(
            this.options().findIndex((option) => option.id === selected),
            0
        );
    }

    private revealActiveOption(): void {
        afterNextRender(
            () => {
                const activeId = this.activeOption()?.elementId;
                const element = this.optionElements().find((option) => option.nativeElement.id === activeId);
                element?.nativeElement.scrollIntoView?.({ block: 'nearest' });
            },
            { injector: this.injector }
        );
    }
}

function layoutBoundaryOf(element: HTMLElement): DOMRect | null {
    const view = element.ownerDocument.defaultView;
    for (let parent = element.parentElement; parent && view; parent = parent.parentElement) {
        const style = view.getComputedStyle(parent);
        const isColumnFlow = style.columnCount !== '' && style.columnCount !== 'auto';
        if (isColumnFlow || style.overflowY !== 'visible') {
            return parent.getBoundingClientRect();
        }
    }
    return null;
}

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

    private readonly pickerInput = viewChild.required<ElementRef<HTMLInputElement>>('pickerInput');
    private readonly optionElements = viewChildren<ElementRef<HTMLElement>>('optionElement');

    protected readonly query = signal('');
    protected readonly isListOpen = signal(false);
    protected readonly activeIndex = signal(0);

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

    ngOnInit(): void {
        const selected = this.selected();
        if (selected !== null) {
            this.query.set(this.labelOf(selected));
        } else if (this.startOpen()) {
            this.isListOpen.set(true);
        }
    }

    focus(): void {
        this.pickerInput().nativeElement.focus();
    }

    close(): void {
        this.isListOpen.set(false);
    }

    protected onQueryInput(value: string): void {
        this.query.set(value);
        this.selected.set(null);
        this.activeIndex.set(0);
        this.isListOpen.set(true);
    }

    protected openList(): void {
        if (!this.isListOpen()) {
            this.activeIndex.set(this.selectedOptionIndex());
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

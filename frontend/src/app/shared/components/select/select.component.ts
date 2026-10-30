import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { NgClass } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    model,
    output,
    signal,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { deepEqual } from '@shared/utils';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

export interface SelectItem<T = unknown> {
    name: string;
    tip?: string;
    subtitle?: string;
    value: T;
    group?: string;
    icon?: string;
    /** Shown, but not selectable: an option the user may not pick, such as a venv whose build failed. */
    disabled?: boolean;
    /** Secondary text between the name and `tip`, muted and truncated: what the option carries,
     *  such as the libraries a venv installs. */
    meta?: string;
    /** CSS color for `tip`, where the text carries a state of its own (a build still running). */
    tipColor?: string;
    /** CSS color (e.g. `var(--success-color)`) of a dot shown before the name, in the trigger, options and readonly value. */
    dotColor?: string;
    /** app-svg-icon id for an optional trailing action button rendered at the end of the item row (e.g. edit-pencil). */
    trailingActionIcon?: string;
}

interface SelectItemGroup {
    group: string | null;
    items: SelectItem[];
}

export type SelectVariant = 'default' | 'boxed';

let nextSelectId = 0;

@Component({
    selector: 'app-select',
    imports: [NgClass, OverlayModule, TooltipComponent, AppSvgIconComponent],
    templateUrl: './select.component.html',
    styleUrls: ['./select.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: SelectComponent,
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SelectComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    loading = input<boolean>(false);
    mod = input<'default' | 'small'>('default');
    items = input<SelectItem[]>([]);
    placeholder = input<string>('Select option');
    invalid = input<boolean>(false);
    disabled = input<boolean>(false);
    hideTrigger = input<boolean>(false);
    panelClass = input<string | string[]>('');
    variant = input<SelectVariant>('default');
    showSearch = input<boolean>(false);
    showCreate = input<boolean>(false);
    /**
     * Render each item under a heading taken from its `group`. Off by default: panels that
     * already set `group` on their items were written before any heading was rendered.
     */
    grouped = input<boolean>(false);
    searchPlaceholder = input<string>('Search...');
    transparent = input<boolean>(false);
    searchNotFoundText = input<string>('No items available');
    /** When true, the selected item's tip is shown at the end of the closed trigger too, not only in the list. */
    showTipInTrigger = input<boolean>(false);
    /** When true, the user can commit the search text as a custom value (Enter or clicking the "Use ..." row). */
    allowCustomValue = input<boolean>(false);
    /**
     * When true, renders the selected value as plain text instead of an interactive trigger.
     * Semantically distinct from `disabled` (which shows a greyed-out clickable control).
     * Use this for read-only permission views.
     */
    readonly = input<boolean>(false);
    /** Text shown in readonly mode when no value is selected. */
    readonlyEmptyPlaceholder = input<string>('—');
    /**
     * Id of an external element that names the select (e.g. a column header). The trigger is then
     * labelled by that element and by its own text, so the selected value is still announced.
     */
    ariaLabelledby = input<string | null>(null);
    /**
     * Stable `data-tour` anchor for the dropdown panel. The panel renders in a CDK overlay outside this host, so an
     * attribute on the host cannot reach it.
     */
    dropdownDataAnchor = input<string | null>(null);

    changed = output<unknown>();
    opened = output<void>();
    onCreate = output<void>();

    selectedValue = model<unknown | null>(null);

    open = signal(false);
    protected readonly search = signal('');

    protected readonly filteredItems = computed<SelectItem[]>(() => {
        const term = this.search().toLowerCase().trim();
        if (!term) return this.items();
        return this.items().filter((i) => i.name.toLowerCase().includes(term));
    });
    /**
     * The options as the panel lays them out: one headingless group when grouping is off, so
     * the template has a single shape to render.
     *
     * Items without a `group` come first and keep no heading -- a picker's leading row, such
     * as a "none" option. They are fixed rows: the search narrows the groups under them and
     * leaves them where they are, so the way out of a search is always on screen.
     *
     * Groups follow in the order they first appear, and the order inside each one is the
     * order of `items`, so a sort the caller applied survives the split. They are built from
     * `filteredItems`, so a search narrows within the groups instead of collapsing them.
     */
    protected readonly groupedItems = computed<SelectItemGroup[]>(() => {
        const items = this.filteredItems();
        if (!this.grouped()) return [{ group: null, items }];

        const pinned = this.items().filter((item) => !item.group);
        const buckets = new Map<string, SelectItem[]>();
        for (const item of items) {
            if (!item.group) continue;
            const bucket = buckets.get(item.group);
            if (bucket) bucket.push(item);
            else buckets.set(item.group, [item]);
        }
        return [
            ...(pinned.length ? [{ group: null, items: pinned }] : []),
            ...[...buckets].map(([group, bucketItems]) => ({ group, items: bucketItems })),
        ];
    });

    /** Whether the panel has a row to show. Not `filteredItems`: in a grouped panel the fixed
     *  rows survive a search, and an "empty" notice under them would contradict them. */
    protected readonly hasVisibleItems = computed(() => this.groupedItems().some((group) => group.items.length > 0));

    protected readonly triggerId = `app-select-trigger-${nextSelectId++}`;
    protected readonly triggerLabelledBy = computed(() => {
        const labelId = this.ariaLabelledby();
        return labelId ? `${labelId} ${this.triggerId}` : null;
    });
    private controlDisabled = signal(false);
    isDisabled = computed(() => this.disabled() || this.controlDisabled());

    selectedItem = computed(() => {
        const value = this.selectedValue();
        if (value === undefined || value === null) return null;

        return this.items().find((i) => deepEqual(i.value, value)) ?? null;
    });

    protected readonly hasExactMatch = computed(() => {
        const term = this.search().trim().toLowerCase();
        if (!term) return true;
        return this.items().some((i) => i.name.toLowerCase() === term);
    });

    protected readonly displayText = computed<string>(() => {
        const item = this.selectedItem();
        if (item) return item.name;
        const value = this.selectedValue();
        if (this.allowCustomValue() && typeof value === 'string' && value.length) return value;
        return this.placeholder();
    });

    /**
     * Value to render in readonly mode: the selected item's name, or a custom-value string
     * (when allowed), or the readonly empty placeholder. Never falls back to the interactive
     * placeholder text.
     */
    protected readonly readonlyDisplayText = computed<string>(() => {
        const item = this.selectedItem();
        if (item) return item.name;
        const value = this.selectedValue();
        if (this.allowCustomValue() && typeof value === 'string' && value.length) return value;
        return this.readonlyEmptyPlaceholder();
    });

    private onChange: (value: unknown) => void = () => {};
    private onTouched: () => void = () => {};

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: TemplateRef<unknown>;

    private overlayRef!: OverlayRef;

    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);
    private destroyRef = inject(DestroyRef);

    toggle() {
        if (this.isDisabled() || this.readonly()) return;
        this.open() ? this.close() : this.openDropdown();
    }

    openDropdown() {
        this.openAt(this.triggerBtn.nativeElement);
    }

    /** Opens the dropdown anchored to originElement. Useful with hideTrigger + a projected trigger. */
    openAt(originElement: HTMLElement, minWidth = 160) {
        if (this.isDisabled() || this.readonly()) return;
        this.opened.emit();
        this.search.set('');

        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(originElement)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
                { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(false);

        if (this.overlayRef) {
            this.overlayRef.detach();
            this.overlayRef.dispose();
            this.overlayRef = undefined!;
        }

        const panelWidth = Math.max(originElement.offsetWidth || 0, minWidth);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'transparent-backdrop',
            panelClass: this.panelClass() || undefined,
            minWidth: panelWidth,
            width: panelWidth,
        });

        this.overlayRef
            .backdropClick()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.close());

        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.open.set(true);
    }

    close() {
        if (this.overlayRef) {
            this.overlayRef.detach();
        }
        this.onTouched();
        this.open.set(false);
        this.search.set('');
    }

    select(item: SelectItem) {
        // Guarded here rather than only in the template: every other path into a selection,
        // `commitCustomValue` among them, goes through this method.
        if (item.disabled) return;
        if (this.isDisabled() || this.readonly()) return;
        this.onChange(item.value);
        this.onTouched();

        this.selectedValue.set(item.value);
        this.changed.emit(item.value);
        this.close();
    }

    protected commitCustomValue() {
        if (this.isDisabled() || this.readonly() || !this.allowCustomValue()) return;
        const value = this.search().trim();
        if (!value) return;

        // If it exactly matches an existing item, prefer selecting that item.
        const match = this.items().find((i) => i.name.toLowerCase() === value.toLowerCase());
        if (match) {
            this.select(match);
            return;
        }

        this.onChange(value);
        this.onTouched();
        this.selectedValue.set(value);
        this.changed.emit(value);
        this.close();
    }

    writeValue(value: unknown): void {
        this.selectedValue.set(value);
    }

    registerOnChange(fn: (value: unknown) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.controlDisabled.set(isDisabled);
    }
}

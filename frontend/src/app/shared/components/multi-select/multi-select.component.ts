import { Overlay, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    model,
    OnInit,
    output,
    signal,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons';
import { CheckboxComponent } from '../checkbox/checkbox.component';
import { SelectItem } from '../select/select.component';

interface GroupedItems {
    group: string | null;
    items: SelectItem[];
}

@Component({
    selector: 'app-multi-select',
    imports: [AppSvgIconComponent, CheckboxComponent, ButtonComponent],
    templateUrl: './multi-select.component.html',
    styleUrls: ['./multi-select.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MultiSelectComponent implements OnInit {
    icon = input<string>('');
    label = input<string>('Select items...');
    searchPlaceholder = input<string>('Search...');
    items = input<SelectItem[]>([]);
    selectedValues = model<unknown[]>([]);
    selectionChange = output<unknown[]>();
    /** Emits the group name when a group header's trailing action button (see groupActionIcon) is clicked. */
    groupAction = output<string>();
    /** Emits item.value when an item's trailing action button (see SelectItem.trailingActionIcon) is clicked. */
    itemAction = output<unknown>();

    grouped = input<boolean>(false);
    showSearch = input<boolean>(true);
    checkboxPosition = input<'left' | 'right'>('right');
    color = input<'primary' | 'white'>('primary');
    disabled = input<boolean>(false);
    panelWidth = input<string>('338px');
    panelHeight = input<string>('475px');
    emptyText = input<string>('No items available');

    /** When true the default trigger button is not rendered.
     *  Use openAt(element) to open the dropdown anchored to an external element. */
    hideTrigger = input<boolean>(false);

    /** Maps a group name to an app-svg-icon id, rendered before the group label. */
    groupIcons = input<Record<string, string>>({});
    /** Show a "selected/total" count after each group label. */
    showGroupCounts = input<boolean>(false);
    /** When false, group labels render in natural case instead of uppercase. */
    uppercaseGroupLabels = input<boolean>(true);
    /** Maps a group name to an app-svg-icon id, rendered as a trailing action button on that group's header row.
     *  Groups present here are "pinned": their header is always rendered, even when they have zero items. */
    groupActionIcon = input<Record<string, string>>({});
    /** Show a "Clear Filter" button in the footer that deselects all items without saving. */
    showClearFilter = input<boolean>(false);
    /** Text of the primary (save) button. */
    saveLabel = input<string>('Save Selection');

    isOpen = signal(false);
    search = signal('');
    tempSelected = signal<unknown[]>([]);
    projectedTriggerEl = signal<HTMLElement | null>(null);

    groupedFiltered = computed<GroupedItems[]>(() => {
        const search = this.search().toLowerCase();
        const selected = this.tempSelected();

        const filteredItems = this.items()
            .filter((i) => i.name.toLowerCase().includes(search))
            .sort((a, b) => Number(selected.includes(b.value)) - Number(selected.includes(a.value)));

        // Grouping disabled
        if (!this.grouped()) {
            return [
                {
                    group: null,
                    items: filteredItems,
                },
            ];
        }

        // Grouping enabled
        const map = new Map<string, SelectItem[]>();

        for (const item of filteredItems) {
            const group = item.group ?? 'Other';

            if (!map.has(group)) {
                map.set(group, []);
            }

            map.get(group)!.push(item);
        }

        // Pinned/action groups always render their header, even with zero items, and come first.
        const pinnedGroups = Object.keys(this.groupActionIcon());
        const result: GroupedItems[] = [];

        for (const group of pinnedGroups) {
            result.push({ group, items: map.get(group) ?? [] });
            map.delete(group);
        }

        for (const [group, items] of map.entries()) {
            result.push({ group, items });
        }

        return result;
    });

    readonly hasResults = computed(() => this.groupedFiltered().some((g) => g.items.length > 0));

    readonly groupCounts = computed<Map<string, { selected: number; total: number }>>(() => {
        const map = new Map<string, { selected: number; total: number }>();
        const selected = this.tempSelected();

        for (const item of this.items()) {
            const group = item.group ?? 'Other';

            if (!map.has(group)) {
                map.set(group, { selected: 0, total: 0 });
            }

            const entry = map.get(group)!;
            entry.total += 1;
            if (selected.includes(item.value)) {
                entry.selected += 1;
            }
        }

        return map;
    });

    @ViewChild('triggerBtn') triggerBtn?: ElementRef<HTMLElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: TemplateRef<unknown>;

    private overlayRef!: OverlayRef;

    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);
    private destroyRef = inject(DestroyRef);

    ngOnInit() {
        this.tempSelected.set([...this.selectedValues()]);
    }

    toggle() {
        if (this.disabled()) return;
        this.isOpen() ? this.close() : this.openDropdown();
    }

    openDropdown(): void {
        if (this.disabled()) return;
        const el = this.projectedTriggerEl() ?? this.triggerBtn?.nativeElement;
        if (el) this.openAt(el);
    }

    registerTrigger(el: ElementRef<HTMLElement>): void {
        this.projectedTriggerEl.set(el.nativeElement);
    }

    openAt(originElement: HTMLElement, seedValues?: unknown[]): void {
        if (this.disabled()) return;
        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(originElement)
            .withPositions([
                // Preferred: below, left-aligned with trigger
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                // Below, right-aligned with trigger (when right edge would clip)
                { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
                // Above, left-aligned (when bottom would clip)
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
                // Above, right-aligned (corner)
                { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(false)
            .withFlexibleDimensions(false)
            .withViewportMargin(8);

        if (this.overlayRef) {
            this.overlayRef.detach();
            this.overlayRef.dispose();
            this.overlayRef = undefined!;
        }

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'transparent-backdrop',
        });

        this.overlayRef
            .backdropClick()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.close());

        this.tempSelected.set([...(seedValues ?? this.selectedValues())]);
        this.search.set('');
        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.isOpen.set(true);
    }

    close() {
        if (this.overlayRef) {
            this.overlayRef.detach();
        }
        this.isOpen.set(false);
    }

    isChecked(value: unknown) {
        return this.tempSelected().includes(value);
    }

    /** Distinguishes a Tabler font-icon class (e.g. "ti ti-robot") from an app-svg-icon id. */
    isTablerIcon(icon: string): boolean {
        return icon.startsWith('ti ') || icon.startsWith('ti-');
    }

    toggleValue(value: unknown) {
        const arr = [...this.tempSelected()];
        const i = arr.indexOf(value);
        if (i >= 0) arr.splice(i, 1);
        else arr.push(value);
        this.tempSelected.set(arr);
    }

    onGroupAction(event: Event, group: string): void {
        event.stopPropagation();
        this.groupAction.emit(group);
    }

    onItemAction(event: Event, value: unknown): void {
        event.stopPropagation();
        this.itemAction.emit(value);
    }

    cancel() {
        this.tempSelected.set([...this.selectedValues()]);
        this.close();
    }

    clearFilter() {
        this.tempSelected.set([]);
    }

    save() {
        this.selectionChange.emit(this.tempSelected());
        this.selectedValues.set(this.tempSelected());
        this.close();
    }
}

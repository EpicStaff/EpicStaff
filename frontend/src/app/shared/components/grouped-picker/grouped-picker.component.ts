import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Overlay, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { NgTemplateOutlet, UpperCasePipe } from '@angular/common';
import {
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    output,
    signal,
    TemplateRef,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import { filter } from 'rxjs';

import { TooltipOnOverflowDirective } from '../../directives/tooltip-on-overflow.directive';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

export interface GroupedPickerItem {
    id: string | number;
    name: string;
    /** Listed, but can't be picked. */
    disabled?: boolean;
    /** Listed faded. */
    dimmed?: boolean;
}

export interface GroupedPickerGroup<TItem extends GroupedPickerItem = GroupedPickerItem> {
    id: string | number;
    name: string;
    /** An app-svg-icon name. */
    icon: string;
    items: readonly TItem[];
}

export interface GroupedPickerKey {
    groupId: string | number;
    itemId: string | number;
}

const COLLAPSED_COUNT = 3;

/** A field that opens a searchable list of items in groups (e.g. models by provider) and emits the picked item. */
@Component({
    selector: 'app-grouped-picker',
    imports: [
        CdkTrapFocus,
        MatTooltip,
        NgTemplateOutlet,
        UpperCasePipe,
        AppSvgIconComponent,
        TooltipComponent,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './grouped-picker.component.html',
    styleUrls: ['./grouped-picker.component.scss'],
})
export class GroupedPickerComponent<TItem extends GroupedPickerItem = GroupedPickerItem> {
    readonly groups = input.required<readonly GroupedPickerGroup<TItem>[]>();
    readonly selected = input<GroupedPickerKey | null>(null);
    readonly placeholder = input<string>('Select');
    readonly label = input<string>('');
    readonly icon = input<string>('help_outline');
    readonly required = input<boolean>(false);
    readonly tooltipText = input<string>('');
    readonly disabled = input<boolean>(false);
    readonly loading = input<boolean>(false);
    readonly loadingText = input<string>('Loading...');
    readonly emptyTitle = input<string>('Nothing found');
    readonly emptyText = input<string>('');
    /** Shown under a group that has no items. */
    readonly emptyGroupText = input<string>('');
    /** Rendered at the end of each group header, e.g. an action button. */
    readonly groupActionTemplate = input<TemplateRef<{ $implicit: GroupedPickerGroup<TItem> }> | null>(null);
    /** Rendered after each item's name in its row. */
    readonly itemSuffixTemplate = input<TemplateRef<{ $implicit: TItem }> | null>(null);
    /** Rendered in the trigger after the picked item's name. */
    readonly triggerSuffixTemplate = input<TemplateRef<unknown> | null>(null);
    readonly picked = output<TItem>();
    readonly closed = output<void>();

    protected readonly triggerButton = viewChild.required<ElementRef<HTMLButtonElement>>('triggerButton');
    protected readonly dropdownTemplate = viewChild.required<TemplateRef<unknown>>('dropdownTemplate');

    protected readonly searchQuery = signal('');
    protected readonly isOpen = signal(false);
    protected readonly expandedGroups = signal<ReadonlySet<string | number>>(new Set());

    protected readonly selectedEntry = computed(() => {
        const key = this.selected();
        if (!key) return null;
        const group = this.groups().find((candidate) => candidate.id === key.groupId);
        const item = group?.items.find((candidate) => candidate.id === key.itemId);
        return group && item ? { group, item } : null;
    });

    protected readonly filteredGroups = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const groups = this.groups();
        if (!query) return groups;

        return groups
            .map((group) => {
                if (group.name.toLowerCase().includes(query)) return group;
                const items = group.items.filter((item) => item.name.toLowerCase().includes(query));
                return items.length > 0 ? { ...group, items } : null;
            })
            .filter((group) => group !== null);
    });

    private overlayRef: OverlayRef | null = null;
    private readonly overlay = inject(Overlay);
    private readonly overlayPositionBuilder = inject(OverlayPositionBuilder);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);
    // Disposing the overlay also completes its event streams; the subscriptions end with the component too.
    private readonly disposeOverlayOnDestroy = this.destroyRef.onDestroy(() => this.overlayRef?.dispose());

    protected toggle(): void {
        if (this.isOpen()) this.close();
        else this.openDropdown();
    }

    protected onSearchChange(event: Event): void {
        this.searchQuery.set((event.target as HTMLInputElement).value);
    }

    protected pick(item: TItem): void {
        this.picked.emit(item);
        this.close();
    }

    protected isSelected(group: GroupedPickerGroup<TItem>, item: TItem): boolean {
        const key = this.selected();
        return key?.groupId === group.id && key.itemId === item.id;
    }

    protected isExpanded(group: GroupedPickerGroup<TItem>): boolean {
        return this.expandedGroups().has(group.id);
    }

    protected visibleItems(group: GroupedPickerGroup<TItem>): readonly TItem[] {
        if (this.searchQuery().trim() || this.isExpanded(group)) return group.items;
        return group.items.slice(0, COLLAPSED_COUNT);
    }

    protected isCollapsible(group: GroupedPickerGroup<TItem>): boolean {
        return group.items.length > COLLAPSED_COUNT && !this.searchQuery().trim();
    }

    protected hiddenCount(group: GroupedPickerGroup<TItem>): number {
        return group.items.length - COLLAPSED_COUNT;
    }

    protected toggleExpand(group: GroupedPickerGroup<TItem>): void {
        this.expandedGroups.update((expanded) => {
            const next = new Set(expanded);
            if (next.has(group.id)) next.delete(group.id);
            else next.add(group.id);
            return next;
        });
    }

    private openDropdown(): void {
        if (!this.overlayRef) {
            const trigger = this.triggerButton();
            const positionStrategy = this.overlayPositionBuilder
                .flexibleConnectedTo(trigger)
                .withPositions([
                    { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                    { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
                ])
                .withPush(true);

            this.overlayRef = this.overlay.create({
                positionStrategy,
                scrollStrategy: this.overlay.scrollStrategies.reposition(),
                hasBackdrop: true,
                backdropClass: 'transparent-backdrop',
                width: trigger.nativeElement.offsetWidth,
            });

            this.overlayRef
                .backdropClick()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(() => this.close());
            this.overlayRef
                .keydownEvents()
                .pipe(
                    filter((event) => event.key === 'Escape'),
                    takeUntilDestroyed(this.destroyRef)
                )
                .subscribe(() => this.close());
        }

        this.overlayRef.attach(new TemplatePortal(this.dropdownTemplate(), this.viewContainerRef));
        this.isOpen.set(true);
    }

    private close(): void {
        this.overlayRef?.detach();
        this.closed.emit();
        this.isOpen.set(false);
    }
}

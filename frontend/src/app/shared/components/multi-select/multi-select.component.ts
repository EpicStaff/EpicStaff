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

    grouped = input<boolean>(false);
    showSearch = input<boolean>(true);
    checkboxPosition = input<'left' | 'right'>('right');
    color = input<'primary' | 'white'>('primary');
    disabled = input<boolean>(false);
    showClearFilter = input<boolean>(false);
    saveLabel = input<string>('Save Selection');
    panelWidth = input<string>('338px');
    panelHeight = input<string>('475px');

    /** When true the default trigger button is not rendered.
     *  Use openAt(element) to open the dropdown anchored to an external element. */
    hideTrigger = input<boolean>(false);

    isOpen = signal(false);
    search = signal('');
    tempSelected = signal<unknown[]>([]);

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

        return Array.from(map.entries()).map(([group, items]) => ({
            group,
            items,
        }));
    });

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLElement>;
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
        this.openAt(this.triggerBtn.nativeElement);
    }

    openAt(originElement: HTMLElement, seedValues?: unknown[]): void {
        if (this.disabled()) return;
        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(originElement)
            .withPositions([
                // Below, left-aligned with trigger
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                // Below, right-aligned with trigger (when right edge would clip) — always below,
                // never flips above, so the panel doesn't jump on top of the trigger/other controls.
                { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
            ])
            .withPush(false)
            .withFlexibleDimensions(true)
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

    toggleValue(value: unknown) {
        const arr = [...this.tempSelected()];
        const i = arr.indexOf(value);
        if (i >= 0) arr.splice(i, 1);
        else arr.push(value);
        this.tempSelected.set(arr);
    }

    cancel() {
        this.tempSelected.set([...this.selectedValues()]);
        this.close();
    }

    clearAll() {
        this.tempSelected.set([]);
    }

    save() {
        this.selectionChange.emit(this.tempSelected());
        this.selectedValues.set(this.tempSelected());
        this.close();
    }
}

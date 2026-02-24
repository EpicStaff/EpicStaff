import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    ViewChild,
    ViewContainerRef,
    signal,
    input,
    output, inject, computed, OnInit, model
} from '@angular/core';
import {TemplatePortal} from '@angular/cdk/portal';

import {AppIconComponent} from "../app-icon/app-icon.component";
import {CheckboxComponent} from "../checkbox/checkbox.component";
import {ButtonComponent} from "../buttons";
import {Overlay, OverlayPositionBuilder, OverlayRef} from "@angular/cdk/overlay";
import {SelectItem} from "../select/select.component";

interface GroupedItems {
    group: string | null;
    items: SelectItem[];
}

@Component({
    selector: 'app-multi-select',
    standalone: true,
    imports: [
        AppIconComponent,
        CheckboxComponent,
        ButtonComponent
    ],
    templateUrl: './multi-select.component.html',
    styleUrls: ['./multi-select.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class MultiSelectComponent implements OnInit {
    icon = input<string>('');
    label = input<string>('Select items...');
    searchPlaceholder = input<string>('Search...');
    items = input<SelectItem[]>([]);
    selectedValues = model<unknown[]>([]);
    selectionChange = output<unknown[]>();

    grouped = input<boolean>(false);

    isOpen = signal(false);
    search = signal('');
    tempSelected = signal<any[]>([]);

    groupedFiltered = computed<GroupedItems[]>(() => {
        const search = this.search().toLowerCase();

        const filteredItems = this.items().filter(i =>
            i.name.toLowerCase().includes(search)
        );

        // Grouping disabled
        if (!this.grouped()) {
            return [
                {
                    group: null,
                    items: filteredItems
                }
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
            items
        }));
    });

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: any;

    private overlayRef!: OverlayRef;

    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);

    ngOnInit() {
        this.tempSelected.set([...this.selectedValues()]);
    }

    toggle() {
        this.isOpen() ? this.close() : this.openDropdown();
    }

    openDropdown() {
        if (!this.overlayRef) {
            const positionStrategy = this.overlayPositionBuilder
                .flexibleConnectedTo(this.triggerBtn)
                .withPositions([{
                    originX: 'start',
                    originY: 'bottom',
                    overlayX: 'start',
                    overlayY: 'top',
                    offsetY: 4
                }])
                .withPush(true);

            this.overlayRef = this.overlay.create({
                positionStrategy,
                scrollStrategy: this.overlay.scrollStrategies.reposition(),
                hasBackdrop: true,
                backdropClass: 'transparent-backdrop'
            });

            this.overlayRef.backdropClick().subscribe(() => this.close());
        }

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

    isChecked(value: any) {
        return this.tempSelected().includes(value);
    }

    toggleValue(value: any) {
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

    save() {
        this.selectionChange.emit(this.tempSelected());
        this.selectedValues.set(this.tempSelected());
        this.close();
    }
}

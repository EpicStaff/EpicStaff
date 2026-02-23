import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    ViewContainerRef,
    ViewChild,
    signal,
    input,
    model, output, computed, inject
} from '@angular/core';

import {TemplatePortal} from '@angular/cdk/portal';
import {NgClass} from "@angular/common";
import {Overlay, OverlayPositionBuilder, OverlayRef, OverlayModule} from "@angular/cdk/overlay";

export interface SelectItem {
    name: string;
    tip?: string;
    value: unknown;
    group?: string;
}

@Component({
    selector: 'app-select',
    standalone: true,
    imports: [NgClass, OverlayModule],
    templateUrl: './select.component.html',
    styleUrls: ['./select.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class SelectComponent {
    mod = input<'default' | 'small'>('default');
    items = input<SelectItem[]>([]);
    placeholder = input<string>('Select option');
    invalid = input<boolean>(false);

    selectedValue = model<unknown | null>(null);
    selectedItem = computed(() => {
        const value = this.selectedValue();
        if (value === undefined || value === null) return null;

        return this.items().find(i => i.value === value) ?? null;
    });

    changed = output<any>();

    open = signal(false);

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: any;

    private overlayRef!: OverlayRef;

    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);

    toggle() {
        this.open() ? this.close() : this.openDropdown();
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
                backdropClass: 'transparent-backdrop',
                width: this.triggerBtn.nativeElement.offsetWidth
            });

            this.overlayRef.backdropClick().subscribe(() => this.close());
        }

        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.open.set(true);
    }

    close() {
        if (this.overlayRef) {
            this.overlayRef.detach();
        }
        this.open.set(false);
    }

    select(item: SelectItem) {
        this.selectedValue.set(item.value);
        this.changed.emit(item.value);
        this.close();
    }
}

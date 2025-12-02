import {
    Component,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    ElementRef,
    inject,
    output,
    signal,
    computed,
    effect,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ValuePreviewTooltipComponent } from './value-preview-tooltip/value-preview-tooltip.component';

export interface AutocompleteItem {
    key: string;
    path: string;
    value: any;
    type: 'group' | 'value';
}

@Component({
    selector: 'app-autocomplete-overlay',
    standalone: true,
    imports: [CommonModule, ValuePreviewTooltipComponent],
    templateUrl: './autocomplete-overlay.component.html',
    styleUrls: ['./autocomplete-overlay.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AutocompleteOverlayComponent {
    private cdr = inject(ChangeDetectorRef);
    private elementRef = inject(ElementRef);
    
    public items = signal<AutocompleteItem[]>([]);
    public currentPath = signal<string[]>([]);
    public filterText = signal<string>('');
    
    public itemSelected = output<AutocompleteItem>();
    public navigateUp = output<void>();
    public navigateDown = output<AutocompleteItem>();
    public navigateToPath = output<number>(); 

    public activeItem = signal<AutocompleteItem | null>(null);
    public tooltipPosition = signal<'left' | 'right'>('right');

    public filteredItems = computed(() => {
        const filter = this.filterText().toLowerCase();
        const allItems = this.items();
        if (!filter) return allItems;
        
        return allItems.filter(item => 
            item.key.toLowerCase().includes(filter)
        );
    });

    public hoveredItem = signal<AutocompleteItem | null>(null);

    constructor() {
        // Effect to reset active item when filtered items change
        effect(() => {
            const items = this.filteredItems();
            if (items.length > 0) {
                this.activeItem.set(items[0]);
            } else {
                this.activeItem.set(null);
            }
        });
    }
    
    // Public method to update data and force refresh (for dynamic component usage)
    public updateData(items: AutocompleteItem[], path: string[], filter: string): void {
        this.items.set(items);
        this.currentPath.set(path);
        this.filterText.set(filter);
        this.cdr.detectChanges();
    }

    public selectItem(item: AutocompleteItem): void {
        this.itemSelected.emit(item);
    }

    public onBackClick(event: MouseEvent): void {
        event.stopPropagation();
        event.preventDefault();
        this.navigateUp.emit();
    }
    
    public onCrumbClick(event: MouseEvent, index: number): void {
        event.stopPropagation();
        event.preventDefault();
        // Emit the target path index (-1 for root, or specific index)
        this.navigateToPath.emit(index);
    }
    
    public typeof(value: any): string {
        if (value === null) return 'null';
        if (Array.isArray(value)) return 'array';
        return typeof value;
    }

    public onArrowClick(event: MouseEvent, item: AutocompleteItem): void {
        event.stopPropagation();
        event.preventDefault();
        this.navigateDown.emit(item);
    }

    public onMouseEnter(item: AutocompleteItem): void {
        this.activeItem.set(item);
        this.hoveredItem.set(item);
        this.calculateTooltipPosition();
    }
    
    private calculateTooltipPosition(): void {
        const el = this.elementRef.nativeElement;
        const rect = el.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const tooltipWidth = 300; // Approximate tooltip width
        
        // Check if there's enough space on the right
        const spaceOnRight = viewportWidth - rect.right;
        const spaceOnLeft = rect.left;
        
        if (spaceOnRight >= tooltipWidth + 16) {
            this.tooltipPosition.set('right');
        } else if (spaceOnLeft >= tooltipWidth + 16) {
            this.tooltipPosition.set('left');
        } else {
            // Default to whichever side has more space
            this.tooltipPosition.set(spaceOnRight >= spaceOnLeft ? 'right' : 'left');
        }
    }

    public onMouseLeave(): void {
        this.hoveredItem.set(null);
    }

    public selectActive(): void {
        const active = this.activeItem();
        if (active) {
            this.selectItem(active);
        }
    }

    public navigateNext(): void {
        const items = this.filteredItems();
        if (items.length === 0) return;

        const currentIndex = items.indexOf(this.activeItem() as AutocompleteItem);
        const nextIndex = (currentIndex + 1) % items.length;
        this.activeItem.set(items[nextIndex]);
    }

    public navigatePrev(): void {
        const items = this.filteredItems();
        if (items.length === 0) return;

        const currentIndex = items.indexOf(this.activeItem() as AutocompleteItem);
        const prevIndex = (currentIndex - 1 + items.length) % items.length;
        this.activeItem.set(items[prevIndex]);
    }
}


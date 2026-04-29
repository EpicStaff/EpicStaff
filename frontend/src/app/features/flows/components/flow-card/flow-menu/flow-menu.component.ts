import { NgClass, NgIf } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    effect,
    ElementRef,
    EventEmitter,
    inject,
    Input,
    OnDestroy,
    Output,
    signal,
} from '@angular/core';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { FlowMenuItemComponent } from './flow-menu-item/flow-menu-item.component';

@Component({
    selector: 'app-flow-menu',
    standalone: true,
    imports: [NgIf, NgClass, FlowMenuItemComponent, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './flow-menu.component.html',
    styleUrls: ['./flow-menu.component.scss'],
})
export class FlowMenuComponent implements OnDestroy {
    @Input() public isOpen = false;
    @Output() public menuToggle = new EventEmitter<boolean>();
    @Output() public actionSelected = new EventEmitter<string>();

    private readonly elementRef = inject(ElementRef);
    private readonly isMouseOnButton = signal<boolean>(false);
    private readonly isMouseOnMenu = signal<boolean>(false);
    public readonly isMenuOpen = signal<boolean>(false);
    public readonly openUpwards = signal<boolean>(false);
    private closeTimeout: ReturnType<typeof setTimeout> | null = null;
    // Approximate menu height (6 items * ~36px + paddings/divider). Used before the menu is rendered
    // so we can decide the open direction without a flash of mis-positioned content.
    private static readonly ESTIMATED_MENU_HEIGHT = 240;

    constructor() {
        effect(() => {
            this.isMenuOpen.set(this.isOpen);
        });
    }

    public toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        const newState = !this.isMenuOpen();
        if (newState) {
            this.updateOpenDirection();
        }
        this.isMenuOpen.set(newState);
        if (newState) {
            this.cancelCloseTimeout();

            this.isMouseOnButton.set(true);
            this.isMouseOnMenu.set(false);
        }
        this.menuToggle.emit(newState);
    }

    private updateOpenDirection(): void {
        const button: HTMLElement | null = this.elementRef.nativeElement?.querySelector('.menu-button');
        if (!button) return;
        const rect = button.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom;
        this.openUpwards.set(spaceBelow < FlowMenuComponent.ESTIMATED_MENU_HEIGHT && rect.top > spaceBelow);
    }

    public onButtonEnter(): void {
        this.isMouseOnButton.set(true);
        this.cancelCloseTimeout();
    }

    public onButtonLeave(): void {
        this.isMouseOnButton.set(false);
        this.scheduleClose();
    }

    public onMenuEnter(): void {
        this.isMouseOnMenu.set(true);
        this.cancelCloseTimeout();
    }

    public onMenuLeave(): void {
        this.isMouseOnMenu.set(false);
        this.scheduleClose();
    }

    private scheduleClose(): void {
        // Only schedule close if menu is open and mouse is not on button or menu
        if (this.isMenuOpen() && !this.isMouseOnButton() && !this.isMouseOnMenu()) {
            this.closeTimeout = setTimeout(() => {
                // Double-check conditions before closing
                if (this.isMenuOpen() && !this.isMouseOnButton() && !this.isMouseOnMenu()) {
                    this.close();
                }
            }, 100); // 100ms delay to allow mouse to travel between button and menu
        }
    }

    private cancelCloseTimeout(): void {
        if (this.closeTimeout) {
            clearTimeout(this.closeTimeout);
            this.closeTimeout = null;
        }
    }

    public close(): void {
        this.cancelCloseTimeout();
        this.isMenuOpen.set(false);
        this.menuToggle.emit(false);
        // Reset states
        this.isMouseOnButton.set(false);
        this.isMouseOnMenu.set(false);
    }

    public onActionClick(event: MouseEvent, action: string): void {
        event.stopPropagation();
        if (this.isMenuOpen()) {
            this.actionSelected.emit(action);
            this.close();
        }
    }

    ngOnDestroy(): void {
        this.cancelCloseTimeout();
    }
}

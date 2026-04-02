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

import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { ProjectMenuItemComponent } from './project-menu-item/project-menu-item.component';

@Component({
    selector: 'app-project-menu',
    standalone: true,
    imports: [NgIf, NgClass, ProjectMenuItemComponent, AppIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './project-menu.component.html',
    styleUrls: ['./project-menu.component.scss'],
})
export class ProjectMenuComponent implements OnDestroy {
    @Input() public isOpen = false;
    @Output() public menuToggle = new EventEmitter<boolean>();
    @Output() public actionSelected = new EventEmitter<string>();

    private readonly elementRef = inject(ElementRef);
    private readonly isMouseOnButton = signal<boolean>(false);
    private readonly isMouseOnMenu = signal<boolean>(false);
    public readonly isMenuOpen = signal<boolean>(false);
    private closeTimeout: ReturnType<typeof setTimeout> | null = null;

    constructor() {
        effect(() => {
            this.isMenuOpen.set(this.isOpen);
        });
    }

    public toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        const newState = !this.isMenuOpen();
        this.isMenuOpen.set(newState);
        if (newState) {
            this.cancelCloseTimeout();

            this.isMouseOnButton.set(true);
            this.isMouseOnMenu.set(false);
        }
        this.menuToggle.emit(newState);
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
        if (this.isMenuOpen() && !this.isMouseOnButton() && !this.isMouseOnMenu()) {
            this.closeTimeout = setTimeout(() => {
                if (this.isMenuOpen() && !this.isMouseOnButton() && !this.isMouseOnMenu()) {
                    this.close();
                }
            }, 100);
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

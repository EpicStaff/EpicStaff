import { CommonModule } from '@angular/common';
import { Component, Input, input } from '@angular/core';

import { CollapseOnOverflowDirective } from '../../../directives/collapse-on-overflow.directive';
import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-button',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, CollapseOnOverflowDirective],
    templateUrl: './button.component.html',
    styleUrls: ['./button.component.scss'],
})
export class ButtonComponent {
    @Input() type: 'primary' | 'secondary' | 'ghost' | 'icon' | 'outline-primary' | 'outline-secondary' = 'primary';
    @Input() mod: 'default' | 'small' = 'default';
    @Input() leftIcon?: string;
    @Input() leftIconColor?: string;
    @Input() rightIcon?: string;
    @Input() rightIconColor?: string;
    @Input() ariaLabel?: string;
    disabled = input<boolean>(false);

    public shouldCollapseToIcon = false;

    public get hasAnyIcon(): boolean {
        return !!this.leftIcon || !!this.rightIcon;
    }

    public get showLeftIcon(): boolean {
        return !!this.leftIcon;
    }

    public get showRightIcon(): boolean {
        if (!this.rightIcon) return false;
        if (!this.shouldCollapseToIcon) return true;
        return !this.leftIcon;
    }

    public get collapseEnabled(): boolean {
        return this.type !== 'icon' && this.hasAnyIcon;
    }

    public onCollapseChange(collapsed: boolean): void {
        this.shouldCollapseToIcon = collapsed;
    }
}
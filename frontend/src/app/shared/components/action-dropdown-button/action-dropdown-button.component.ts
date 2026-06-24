import { OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

export interface ActionDropdownItem {
    label: string;
    value: string;
}

@Component({
    selector: 'app-action-dropdown-button',
    standalone: true,
    imports: [OverlayModule, AppSvgIconComponent, CommonModule, MatTooltipModule],
    templateUrl: './action-dropdown-button.component.html',
    styleUrls: ['./action-dropdown-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActionDropdownButtonComponent {
    label = input.required<string>();
    leftIcon = input<string | undefined>(undefined);
    items = input.required<ActionDropdownItem[]>();
    disabled = input<boolean>(false);
    loading = input<boolean>(false);

    mainClick = output<void>();
    itemClick = output<ActionDropdownItem>();

    protected isOpen = signal(false);

    protected toggle(event: Event): void {
        event.stopPropagation();
        this.isOpen.update((v) => !v);
    }

    protected close(): void {
        this.isOpen.set(false);
    }

    protected onMainClick(): void {
        this.close();
        this.mainClick.emit();
    }

    protected onItemClick(item: ActionDropdownItem): void {
        this.close();
        this.itemClick.emit(item);
    }
}

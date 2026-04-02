import { animate, style, transition, trigger } from '@angular/animations';
import { NgFor, NgIf } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnInit, Output } from '@angular/core';

import { AppIconComponent } from '../../app-icon/app-icon.component';

// Icon dictionary mapping icon names to their paths
export const UI_ICONS: Record<string, string> = {
    // Navigation & UI
    'arrow-left': 'ui/arrow-left',
    'chevron-up': 'ui/chevron-up',
    'chevron-down': 'ui/chevron-down',
    x: 'ui/x',

    // Actions
    check: 'ui/check',
    plus: 'ui/plus',
    search: 'ui/search',
    upload: 'ui/upload',

    // Common
    star: 'ui/star',
    'tags-filled': 'ui/tags-filled',
    'tags-outline': 'ui/tags-outline',
    'dots-vertical': 'ui/dots-vertical',
    'horizontal-dots': 'ui/horizontal-dots',

    // Data & Files
    database: 'ui/database',
    files: 'ui/files',
    photo: 'ui/photo',
    scraping: 'ui/scraping',

    // Other
    email: 'ui/email',
    'filter-filled': 'ui/filter-filled',
    'filter-outline': 'ui/filter-outline',
    python: 'ui/python',
};

@Component({
    selector: 'app-icon-picker',
    standalone: true,
    imports: [NgFor, NgIf, AppIconComponent],
    templateUrl: './icon-picker.component.html',
    styleUrls: ['./icon-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    animations: [
        // Fade animation for icon picker
        trigger('fadeInOut', [
            transition(':enter', [
                style({ opacity: 0, transform: 'translateY(-4px)' }),
                animate('200ms ease', style({ opacity: 1, transform: 'translateY(0)' })),
            ]),
            transition(':leave', [animate('200ms ease', style({ opacity: 0, transform: 'translateY(-4px)' }))]),
        ]),
    ],
})
export class IconPickerComponent implements OnInit {
    @Input() selectedIcon: string | null = null;
    @Output() iconSelected = new EventEmitter<string | null>();

    public showIconPicker = false;
    public uiIcons = UI_ICONS;

    // All available icons as a simple array
    public get availableIcons(): string[] {
        return Object.keys(this.uiIcons);
    }

    constructor() {}

    ngOnInit(): void {
        // Set default icon if not provided (use the first available icon)
        if (!this.selectedIcon) {
            this.selectedIcon = 'star';
            this.iconSelected.emit(this.selectedIcon);
        }
    }

    getIconPath(iconName: string): string {
        return this.uiIcons[iconName] || '';
    }

    toggleIconPicker(): void {
        this.showIconPicker = !this.showIconPicker;
        if (this.showIconPicker) {
            setTimeout(() => {
                document.addEventListener('click', this.closeIconPickerOnClickOutside);
            });
        } else {
            document.removeEventListener('click', this.closeIconPickerOnClickOutside);
        }
    }

    closeIconPickerOnClickOutside = (event: Event) => {
        const iconPicker = document.querySelector('.icon-picker-popup');
        const iconButton = document.querySelector('.icon-selector');
        if (
            iconPicker &&
            !iconPicker.contains(event.target as Node) &&
            iconButton &&
            !iconButton.contains(event.target as Node)
        ) {
            this.showIconPicker = false;
            document.removeEventListener('click', this.closeIconPickerOnClickOutside);
        }
    };

    selectIcon(iconName: string): void {
        this.selectedIcon = iconName;
        this.iconSelected.emit(iconName);
        this.showIconPicker = false;
    }

    clearIcon(): void {
        this.selectedIcon = null;
        this.iconSelected.emit(null);
    }
}

import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterModule } from '@angular/router';

@Component({
    selector: 'app-go-to-button',
    standalone: true,
    imports: [CommonModule, RouterModule, MatTooltipModule],
    templateUrl: './go-to-button.component.html',
    styleUrl: './go-to-button.component.scss',
})
export class GoToButtonComponent {
    @Input() href: string | null = null;
    @Input() target: '_self' | '_blank' = '_self';
    @Input() variant: 'icon' | 'full' = 'icon';
    @Input() label: string = 'Go to flow';
    @Input() route: string | unknown[] = '/';
    @Input() disabled = false;
}

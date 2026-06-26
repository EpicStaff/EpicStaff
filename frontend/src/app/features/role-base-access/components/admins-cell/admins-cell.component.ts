import { NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, ElementRef, inject, input, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';
import { OrgAdmin } from '@shared/models';

import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-admins-cell',
    templateUrl: './admins-cell.component.html',
    styleUrls: ['./admins-cell.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [UserAvatarComponent, AppSvgIconComponent, NgStyle, MatTooltipModule, ClickOutsideDirective],
})
export class AdminsCellComponent {
    admins = input.required<OrgAdmin[]>();

    isOpen = signal(false);
    panelStyle = signal<Record<string, string>>({});

    private readonly elRef = inject(ElementRef<HTMLElement>);

    // Uses position:fixed + getBoundingClientRect() instead of position:absolute
    // because the table body has overflow-y:auto which would clip an absolute panel.
    toggle(event: Event): void {
        event.stopPropagation();
        if (this.isOpen()) {
            this.isOpen.set(false);
            return;
        }
        const rect = (this.elRef.nativeElement as HTMLElement).getBoundingClientRect();
        this.panelStyle.set({
            top: `${rect.bottom + 4}px`,
            left: `${rect.left}px`,
        });
        this.isOpen.set(true);
    }

    stopProp(event: Event): void {
        event.stopPropagation();
    }

    adminName(admin: OrgAdmin): string {
        return admin.display_name || admin.email;
    }
}

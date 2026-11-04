import { CdkTrapFocus } from '@angular/cdk/a11y';
import { NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, input, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, UserAvatarComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';
import { OrgAdmin } from '@shared/models';

@Component({
    selector: 'app-admins-cell',
    templateUrl: './admins-cell.component.html',
    styleUrls: ['./admins-cell.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [UserAvatarComponent, AppSvgIconComponent, NgStyle, MatTooltipModule, ClickOutsideDirective, CdkTrapFocus],
})
export class AdminsCellComponent {
    admins = input.required<OrgAdmin[]>();

    isOpen = signal(false);
    panelStyle = signal<Record<string, string>>({});

    // The collapsed trigger shows two names, so its tooltip names every admin.
    readonly adminsTooltip = computed(
        () =>
            `Admins: ${this.admins()
                .map((admin) => this.adminName(admin))
                .join(', ')}`
    );

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

    // Closing destroys the focus trap, which hands the focus back to the trigger.
    onPanelEscape(event: Event): void {
        event.stopPropagation();
        this.isOpen.set(false);
    }

    adminName(admin: OrgAdmin): string {
        return admin.display_name || admin.email;
    }
}

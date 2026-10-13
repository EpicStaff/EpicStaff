import { Component, computed, input } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { ChatBindingStatus } from '../../utils/binding-status.util';
import { deskAccessibleName, deskAvatarColor, deskBadgeText, deskInitials } from '../../utils/desk-avatar.util';

// Shown for a blank name; the same picture as the sidenav's Chat item.
const FALLBACK_ICON = 'message-circle';

/**
 * A desk's square: its picture (an icon when given, else the initials of its name, on a fill picked by its id), a
 * status mark whose shape differs per status, and a needs-a-person count badge. One image to assistive technology,
 * named in words.
 */
@Component({
    selector: 'app-desk-avatar',
    imports: [AppSvgIconComponent],
    templateUrl: './desk-avatar.component.html',
    styleUrl: './desk-avatar.component.scss',
    host: {
        role: 'img',
        '[attr.aria-label]': 'accessibleName()',
    },
})
export class DeskAvatarComponent {
    readonly name = input.required<string>();
    /** Picks the fill; null for an entry that is not a desk (All desks), which gets the neutral one. */
    readonly deskId = input<string | null>(null);
    /** A sprite icon drawn instead of the initials. */
    readonly icon = input<string | null>(null);
    /** No mark when null. */
    readonly status = input<ChatBindingStatus | null>(null);
    readonly count = input(0);
    /** Off where the count is drawn beside the avatar instead; it stays in the accessible name either way. */
    readonly showBadge = input(true);

    protected readonly initials = computed(() => deskInitials(this.name()));
    protected readonly fill = computed(() => {
        const deskId = this.deskId();
        return deskId === null ? null : deskAvatarColor(deskId);
    });
    protected readonly pictureIcon = computed(() => this.icon() ?? (this.initials() ? null : FALLBACK_ICON));
    protected readonly badge = computed(() => (this.showBadge() ? deskBadgeText(this.count()) : null));
    protected readonly accessibleName = computed(() => deskAccessibleName(this.name(), this.status(), this.count()));
}

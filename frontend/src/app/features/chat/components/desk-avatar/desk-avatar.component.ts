import { Component, computed, input } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { ChatBindingStatus } from '../../utils/binding-status.util';
import { deskAccessibleName, deskBadgeText, deskInitials } from '../../utils/desk-avatar.util';

// Shown for a blank name; the same picture as the sidenav's Conversations item.
const FALLBACK_ICON = 'messages';

/**
 * A desk's square: its picture (an icon when given, else the initials of its name) on the one neutral fill every desk
 * shares, a status mark whose shape differs per status, and a needs-a-person count badge. One image to assistive
 * technology, named in words. A container recolours the fill through `--desk-avatar-fill` (the rail on hover).
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
    /** A sprite icon drawn instead of the initials. */
    readonly icon = input<string | null>(null);
    /** No mark when null. */
    readonly status = input<ChatBindingStatus | null>(null);
    readonly count = input(0);
    /** Off where the count is drawn beside the avatar instead; it stays in the accessible name either way. */
    readonly showBadge = input(true);

    protected readonly initials = computed(() => deskInitials(this.name()));
    protected readonly pictureIcon = computed(() => this.icon() ?? (this.initials() ? null : FALLBACK_ICON));
    protected readonly badge = computed(() => (this.showBadge() ? deskBadgeText(this.count()) : null));
    protected readonly accessibleName = computed(() => deskAccessibleName(this.name(), this.status(), this.count()));
}

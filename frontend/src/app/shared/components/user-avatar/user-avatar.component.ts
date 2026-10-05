import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { getUserInitials } from './user-initials.util';

/**
 * Round user avatar: the avatar image when there is one, otherwise the initials of `name`,
 * otherwise a generic person placeholder (no name, e.g. a user who never set a display name).
 */
@Component({
    selector: 'app-user-avatar',
    imports: [AppSvgIconComponent],
    template: `
        @if (avatarUrl()) {
            <img
                [src]="avatarUrl()"
                alt="User avatar"
                class="avatar-img"
            />
        } @else if (initials()) {
            <span class="initials">{{ initials() }}</span>
        } @else {
            <app-svg-icon
                class="placeholder"
                icon="user"
                size="12px"
            />
        }
    `,
    styles: [
        `
            :host {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background: var(--transparent-white-8);
                color: var(--text-secondary-60);
                font-size: var(--text-body-small-large-size);
                font-weight: var(--text-body-small-large-weight);
                line-height: 1;
                overflow: hidden;
            }

            .initials {
                display: block;
                line-height: 24px;
            }

            .avatar-img {
                width: 100%;
                height: 100%;
                object-fit: cover;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserAvatarComponent {
    readonly name = input.required<string | null>();
    readonly avatarUrl = input<string | null>(null);

    protected readonly initials = computed(() => getUserInitials(this.name()));
}

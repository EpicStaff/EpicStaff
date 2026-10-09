import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

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

    // Letters first ("j0hn" -> "JH"); no letters falls back to raw characters ("007" -> "00").
    readonly initials = computed(() => {
        const name = (this.name() ?? '').trim();
        const visibleName = (name.includes('@') && name.slice(0, name.lastIndexOf('@'))) || name;
        const letterWords = visibleName.split(/\P{L}+/u).filter(Boolean);
        if (letterWords.length >= 2) {
            return (letterWords[0][0] + letterWords[1][0]).toUpperCase();
        }
        if (letterWords.length === 1) {
            return letterWords[0].substring(0, 2).toUpperCase();
        }
        return visibleName.replace(/\s/g, '').substring(0, 2).toUpperCase();
    });
}

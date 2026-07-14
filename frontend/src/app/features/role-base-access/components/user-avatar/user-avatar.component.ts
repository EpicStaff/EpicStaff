import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
    selector: 'app-user-avatar',
    template: `
        @if (avatarUrl()) {
            <img
                [src]="avatarUrl()"
                alt="User avatar"
                class="avatar-img"
            />
        } @else {
            <span class="initials">{{ initials() }}</span>
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
                color: var(--color-text-secondary);
                font-size: var(--font-size-xs);
                font-weight: 500;
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
    name = input.required<string>();
    avatarUrl = input<string | null>(null);

    readonly initials = computed(() => {
        const parts = this.name().trim().split(/\s+/);
        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }
        return parts[0].substring(0, 2).toUpperCase();
    });
}

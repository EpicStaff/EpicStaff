import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
    selector: 'app-user-avatar',
    template: `{{ initials() }}`,
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
                font-size: 12px;
                font-weight: 500;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserAvatarComponent {
    name = input.required<string>();

    readonly initials = computed(() => {
        const parts = this.name().trim().split(/\s+/);
        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }
        return parts[0].substring(0, 2).toUpperCase();
    });
}

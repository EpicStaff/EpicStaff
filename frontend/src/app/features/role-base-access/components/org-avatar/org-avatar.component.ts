import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
    selector: 'app-org-avatar',
    template: `{{ initial() }}`,
    styles: [
        `
            :host {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                width: 24px;
                height: 24px;
                border-radius: var(--radius-sm);
                background: var(--transparent-white-8);
                color: var(--color-text-secondary);
                font-size: var(--font-size-xs);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrgAvatarComponent {
    name = input.required<string>();

    readonly initial = computed(() => this.name().trim()[0]?.toUpperCase() ?? '');
}

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
                border-radius: 4px;
                background: var(--transparent-white-8);
                color: var(--text-secondary-60);
                font-size: 12px;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrgAvatarComponent {
    name = input.required<string>();

    readonly initial = computed(() => this.name().trim()[0]?.toUpperCase() ?? '');
}

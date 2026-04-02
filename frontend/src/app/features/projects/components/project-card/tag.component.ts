import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
    selector: 'app-tag',
    standalone: true,
    template: `<div class="tag-pill">
        <span class="tag-text">{{ tag }}</span>
    </div>`,
    styles: [
        `
            .tag-pill {
                background: rgb(48, 48, 48);
                color: #a0a8b1;
                font-size: 12px;
                padding: 0 0.85em;
                border-radius: 999px;
                font-weight: 400;
                transition:
                    background 0.18s,
                    color 0.18s;
                user-select: none;
                cursor: pointer;
                border: none;
                outline: none;
                display: inline-flex;
                align-items: center;
                height: 22px;
                line-height: 1;
            }
            .tag-pill:hover {
                background: rgb(59, 59, 59);
                color: #e0e3e8;
            }
            .tag-text {
                margin-bottom: 2px;
                display: inline-block;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TagComponent {
    @Input() tag!: string;
}

import { ChangeDetectionStrategy, Component, EventEmitter, Output } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import { AppSvgIconComponent } from '../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-add-project-card',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent],
    template: `
        <div
            class="add-project-card"
            (click)="createClick.emit()"
        >
            <div class="content">
                <div class="plus-icon">
                    <app-svg-icon
                        icon="plus"
                        size="2.5rem"
                    />
                </div>
                <div class="title">Create New Project</div>
            </div>
        </div>
    `,
    styles: [
        `
            .add-project-card {
                background: transparent;
                border-radius: var(--radius-2xl);
                padding: var(--space-2xl);
                color: var(--color-text-primary);
                font-size: var(--font-size-lg);
                display: flex;
                flex-direction: column;
                height: 165px;
                transition: all 0.2s ease;
                position: relative;
                border: 1px dashed var(--graphite-650);
                cursor: pointer;
            }

            .add-project-card:hover {
                border-color: var(--accent-color);
                box-shadow:
                    0 12px 20px var(--black-alpha-18),
                    0 3px 6px var(--black-alpha-10);
            }

            .content {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 100%;
                text-align: center;
            }

            .plus-icon {
                width: 60px;
                height: 60px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-bottom: var(--space-sm);
            }

            .plus-icon app-svg-icon {
                color: var(--accent-color);
                width: 2.5rem;
                height: 2.5rem;
            }

            .title {
                font-size: var(--font-size-lg);
                font-weight: var(--font-weight-medium);
                color: #8b8e98;
                transition: color 0.2s ease;
            }

            .add-project-card:hover .title {
                color: var(--color-text-primary);
            }
        `,
    ],
})
export class AddProjectCardComponent {
    @Output() public createClick = new EventEmitter();
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}

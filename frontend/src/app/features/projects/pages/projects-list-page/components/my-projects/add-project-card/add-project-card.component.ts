import {
    Component,
    ChangeDetectionStrategy,
    Output,
    EventEmitter,
} from '@angular/core';
import { AppIconComponent } from '../../../../../../../shared/components/app-icon/app-icon.component';

@Component({
    selector: 'app-add-project-card',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppIconComponent],
    template: `
        <div class="add-project-card" (click)="createClick.emit()">
            <div class="content">
                <div class="plus-icon">
                    <app-icon icon="ui/plus" size="2.5rem"></app-icon>
                </div>
                <div class="title">Create New Project</div>
            </div>
        </div>
    `,
    styles: [
        `
            .add-project-card {
                background: transparent;
                border-radius: 12px;
                padding: 1.5rem;
                color: var(--color-text-primary);
                font-size: 1rem;
                display: flex;
                flex-direction: column;
                height: 168px;
                transition: all 0.2s ease;
                position: relative;
                border: 1px dashed #3a3e48;
                cursor: pointer;
            }

            .add-project-card:hover {
                border-color: var(--accent-color);
                box-shadow: 0 12px 20px rgba(0, 0, 0, 0.18),
                    0 3px 6px rgba(0, 0, 0, 0.1);
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
                margin-bottom: 0.5rem;
            }

            .plus-icon app-icon {
                color: var(--accent-color);
                width: 2.5rem;
                height: 2.5rem;
            }

            .title {
                font-size: 16px;
                font-weight: 500;
                color: #8b8e98;
                transition: color 0.2s ease;
            }

            .add-project-card:hover .title {
                color: #ffffff;
            }
        `,
    ],
})
export class AddProjectCardComponent {
    @Output() public createClick = new EventEmitter();
}

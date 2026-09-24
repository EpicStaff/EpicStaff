import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { NODE_ICONS, NodeType } from '@shared/models';

import { CreateNodeRequest } from '../../../core/models/node-creation.types';

@Component({
    selector: 'app-persistence-menu',
    template: `
        <ul>
            @if (isVisible()) {
                <li (click)="onSelect()">
                    <i [class]="icon"></i>
                    <span>Persistence</span>
                </li>
            }
        </ul>
    `,
    styles: [
        `
            ul {
                list-style: none;
                padding: 0 16px;
                margin: 0;
            }
            li {
                display: flex;
                align-items: center;
                gap: 16px;
                padding: 12px 16px;
                border-radius: 8px;
                cursor: pointer;
                transition: background 0.2s ease;
            }
            li:hover {
                background: var(--color-surface-card);
                color: var(--color-text-primary);
            }
            li i {
                font-size: 1.125rem;
                color: var(--accent-color);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PersistenceMenuComponent {
    public readonly searchTerm = input('');
    public readonly nodeSelected = output<CreateNodeRequest>();

    public readonly isVisible = computed(() => 'persistence'.includes(this.searchTerm().trim().toLowerCase()));
    public readonly icon = NODE_ICONS[NodeType.PERSISTENCE];

    public onSelect(): void {
        this.nodeSelected.emit({ type: NodeType.PERSISTENCE });
    }
}

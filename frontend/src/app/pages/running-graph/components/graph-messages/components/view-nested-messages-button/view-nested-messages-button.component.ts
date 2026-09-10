import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

// Shared "N messages" drilldown chip. Used on any row that can collapse its inner
// steps into a nested drilldown view (subgraph start row, CDT/classification-decision-table
// start row, ...). Extracted from subgraph-start-message so the markup/CSS lives in one
// place instead of being duplicated per row type.
@Component({
    selector: 'app-view-nested-messages-button',
    imports: [CommonModule, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <button
            class="view-nested-button"
            type="button"
            (click)="onClick($event)"
            [class.show-nested-btn--open]="isOpen()"
        >
            {{ count() }} messages
            <div
                class="play-nested-arrow"
                [class.play-nested-arrow--open]="isOpen()"
            >
                <app-svg-icon
                    icon="caret-right-filled"
                    size="1rem"
                />
            </div>
        </button>
    `,
    styles: [
        `
            /*
             * This component is a direct flex child of the row header (sibling of the
             * <h3> title) in both start-message and subgraph-start-message. The host
             * itself — not the inner button — must own the "push to the right edge"
             * margin, otherwise margin-left: auto on an inline child does nothing.
             */
            :host {
                display: inline-flex;
                align-items: center;
                margin-left: auto;
            }

            .view-nested-button {
                background-color: rgb(0, 191, 165);
                color: rgb(255, 255, 255);
                border: 2px solid rgba(0, 191, 165, 0.4);
                border-radius: 6px;
                padding: 0.5rem 0.75rem;
                font-weight: 500;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                white-space: nowrap;
                flex-shrink: 0;
                cursor: pointer;
                transition:
                    background-color 0.2s ease,
                    border-color 0.2s ease;
            }

            .view-nested-button:hover {
                background-color: transparent;
                color: rgb(0, 191, 165);
                border-color: rgb(0, 191, 165);
            }

            .show-nested-btn--open {
                background-color: transparent;
            }

            .play-nested-arrow {
                margin-top: 2px;
                display: inline-block;
                transform: rotate(0deg);
                transition: transform 0.2s ease;
                color: white;
            }

            .play-nested-arrow--open {
                transition:
                    transform 0.2s ease,
                    color 0.2s ease;
                transform: rotate(90deg);
                color: rgb(0, 191, 165);
            }
        `,
    ],
})
export class ViewNestedMessagesButtonComponent {
    readonly count = input<number>(0);
    readonly isOpen = input<boolean>(false);
    readonly clicked = output<void>();

    onClick(event: Event): void {
        event.stopPropagation();
        this.clicked.emit();
    }
}

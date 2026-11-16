import { Component, input } from '@angular/core';
import { generateUuid } from '@shared/utils';

/** What the backend refused when the flow was last saved, under the field (or atop the panel) it is about. */
@Component({
    selector: 'app-node-save-errors',
    template: `
        @if (messages().length > 0) {
            <ul class="node-save-errors">
                @for (message of messages(); track $index) {
                    <li class="node-save-errors__item">{{ message }}</li>
                }
            </ul>
        }
    `,
    styleUrl: './node-save-errors.component.scss',
    host: { '[attr.id]': 'id()' },
})
export class NodeSaveErrorsComponent {
    public readonly messages = input<readonly string[]>([]);
    /** The host's id, for the field to point its `aria-describedby` at, so the reason is read with the field. */
    public readonly id = input<string>(`node-save-errors-${generateUuid()}`);
}

import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
    selector: 'app-project-templates',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `<p>No templates available yet.</p>`,
    styles: ['p { color: #ccc; padding: var(--space-lg); }'],
})
export class ProjectTemplatesComponent {
    constructor() {}
}

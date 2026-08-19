import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
    selector: 'app-project-templates',
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `<p>No templates available yet.</p>`,
    styles: ['p { color: #ccc; padding: 1rem; }'],
})
export class ProjectTemplatesComponent {
    constructor() {}
}

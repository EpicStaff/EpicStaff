import { ChangeDetectionStrategy, Component, OnInit } from '@angular/core';

@Component({
    selector: 'app-flow-templates',
    standalone: true,
    template: `<p>No templates available yet.</p>`,
    changeDetection: ChangeDetectionStrategy.Eager,
    styles: ['p { color: #ccc; padding: 1rem; }'],
})
export class FlowTemplatesComponent implements OnInit {
    constructor() {}
    ngOnInit(): void {}
}

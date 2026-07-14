import { Component, OnInit } from '@angular/core';

@Component({
    selector: 'app-flow-templates',
    standalone: true,
    template: `<p>No templates available yet.</p>`,
    styles: ['p { color: #ccc; padding: var(--space-lg); }'],
})
export class FlowTemplatesComponent implements OnInit {
    constructor() {}
    ngOnInit(): void {}
}

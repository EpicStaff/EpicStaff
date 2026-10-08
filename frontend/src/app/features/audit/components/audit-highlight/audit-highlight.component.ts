import { Component, computed, input } from '@angular/core';

import { splitByMatch } from '../../utils/split-by-match.util';

@Component({
    selector: 'app-audit-highlight',
    templateUrl: './audit-highlight.component.html',
    styleUrls: ['./audit-highlight.component.scss'],
})
export class AuditHighlightComponent {
    public readonly text = input.required<string>();
    public readonly term = input<string>('');

    protected readonly segments = computed(() => splitByMatch(this.text(), this.term()));
}

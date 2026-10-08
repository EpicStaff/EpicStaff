import { Component, model, signal } from '@angular/core';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';

import { AuditMatchScopeState, MAX_ROWS_BEFORE } from '../../models/audit-filter.models';

@Component({
    selector: 'app-audit-match-scope',
    imports: [AppSvgIconComponent, CheckboxComponent],
    templateUrl: './audit-match-scope.component.html',
    styleUrl: './audit-match-scope.component.scss',
})
export class AuditMatchScopeComponent {
    public scope = model.required<AuditMatchScopeState>();

    protected readonly isExpanded = signal(true);

    protected readonly maxRowsBefore = MAX_ROWS_BEFORE;

    protected readonly fullSessionHint = 'Included in full data on the same session';

    protected toggleExpanded(): void {
        this.isExpanded.update((isExpanded) => !isExpanded);
    }

    protected setChildren(children: boolean): void {
        this.scope.update((current) => ({ ...current, children }));
    }

    protected setRowsBeforeEnabled(rowsBeforeEnabled: boolean): void {
        this.scope.update((current) => ({ ...current, rowsBeforeEnabled }));
    }

    protected setFullSessionHistory(fullSessionHistory: boolean): void {
        this.scope.update((current) => ({ ...current, fullSessionHistory }));
    }

    protected setRowsBefore(event: Event): void {
        const inputElement = event.target as HTMLInputElement;
        const rowsBefore = Math.min(Math.max(Math.trunc(Number(inputElement.value)) || 1, 1), MAX_ROWS_BEFORE);
        // [value] does not revert the DOM when the clamped string equals the old one
        inputElement.value = String(rowsBefore);
        // typing a count opts in
        this.scope.update((current) => ({ ...current, rowsBefore, rowsBeforeEnabled: true }));
    }
}

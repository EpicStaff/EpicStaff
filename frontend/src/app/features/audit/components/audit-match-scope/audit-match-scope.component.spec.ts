import { TestBed } from '@angular/core/testing';

import { DEFAULT_MATCH_SCOPE, EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { compileAuditFilter } from '../../utils/compile-audit-filter.util';
import { AuditMatchScopeComponent } from './audit-match-scope.component';

function render() {
    const fixture = TestBed.createComponent(AuditMatchScopeComponent);
    fixture.componentRef.setInput('scope', DEFAULT_MATCH_SCOPE);
    fixture.detectChanges();
    const [, children, rowsBefore, fullHistory] = Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLInputElement>('input[type="checkbox"]')
    );
    const click = (checkbox: HTMLInputElement) => {
        checkbox.click();
        fixture.detectChanges();
    };
    return { scope: () => fixture.componentInstance.scope(), children, rowsBefore, fullHistory, click };
}

describe('AuditMatchScopeComponent', () => {
    it('checks the narrower scopes and keeps them enabled when full history is picked', () => {
        const { scope, children, rowsBefore, fullHistory, click } = render();

        click(fullHistory);

        expect(scope()).toMatchObject({ fullSessionHistory: true, children: true, rowsBeforeEnabled: true });
        expect(children.checked).toBe(true);
        expect(rowsBefore.checked).toBe(true);
        expect(children.disabled).toBe(false);
        expect(rowsBefore.disabled).toBe(false);
    });

    it('drops full history when a narrower scope is unchecked, so the compiled scope matches the boxes', () => {
        const { scope, children, fullHistory, click } = render();

        click(fullHistory);
        click(children);

        expect(fullHistory.checked).toBe(false);
        expect(compileAuditFilter({ ...EMPTY_AUDIT_FILTER, matchScope: scope() }).matchScope).toEqual({
            ancestors: true,
            children: false,
            rows_before: 1,
        });
    });
});

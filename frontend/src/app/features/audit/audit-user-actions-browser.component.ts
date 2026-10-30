import { Component } from '@angular/core';

@Component({
    selector: 'app-audit-user-actions-browser',
    template: `
        <div class="audit-user-actions">
            <p class="audit-user-actions__empty">No user actions to show yet.</p>
        </div>
    `,
    styles: `
        .audit-user-actions {
            padding: 16px 20px 12px;
            color: var(--color-text-primary);
        }

        .audit-user-actions__empty {
            margin: 0;
            color: var(--color-ks-transparent-text-60);
        }
    `,
})
export class AuditUserActionsBrowserComponent {}

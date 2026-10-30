import { Component } from '@angular/core';

@Component({
    selector: 'app-audit-user-actions-browser',
    template: `
        <div class="audit-user-actions">
            <h1 class="audit-user-actions__title">User actions</h1>
            <p class="audit-user-actions__empty">No user actions to show yet.</p>
        </div>
    `,
    styles: `
        .audit-user-actions {
            padding: 16px 20px 12px;
            color: var(--color-text-primary);
        }

        .audit-user-actions__title {
            margin: 0 0 8px;
            font-size: var(--text-h1-size);
            font-weight: var(--text-h1-weight);
            line-height: var(--text-h1-line-height);
        }

        .audit-user-actions__empty {
            margin: 0;
            color: var(--color-ks-transparent-text-60);
        }
    `,
})
export class AuditUserActionsBrowserComponent {}

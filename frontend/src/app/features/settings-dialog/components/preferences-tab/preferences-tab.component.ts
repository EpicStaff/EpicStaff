import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
    selector: 'app-preferences-tab',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="tab-content">
            <div class="tab-header">
                <div>
                    <h3 class="title">Preferences</h3>
                    <p class="subtitle">Customize your application settings and preferences</p>
                </div>
            </div>

            <p>User preferences configuration will go here.</p>
        </div>
    `,
    styles: [
        `
            .tab-content {
                padding: 1.25rem;
            }

            .tab-header {
                margin-bottom: 1.5rem;
            }

            .title {
                font-size: 20px;
                font-weight: 600;
                color: var(--color-text-primary);
                margin-top: 0;
                margin-bottom: 8px;
            }

            .subtitle {
                font-size: 14px;
                color: var(--color-text-secondary);
                margin-top: 0;
            }

            p {
                color: var(--color-text-secondary);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PreferencesTabComponent {}

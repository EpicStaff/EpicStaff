import { ChangeDetectionStrategy, Component, output, signal } from '@angular/core';

export type AuditFilterTab = 'builder' | 'query' | 'presets';

@Component({
    selector: 'app-audit-filters-panel',
    standalone: true,
    imports: [],
    templateUrl: './audit-filters-panel.component.html',
    styleUrls: ['./audit-filters-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFiltersPanelComponent {
    public readonly closed = output<void>();
    public readonly applied = output<void>();
    public readonly cleared = output<void>();

    public activeTab = signal<AuditFilterTab>('builder');

    public setActiveTab(tab: AuditFilterTab): void {
        this.activeTab.set(tab);
    }
}

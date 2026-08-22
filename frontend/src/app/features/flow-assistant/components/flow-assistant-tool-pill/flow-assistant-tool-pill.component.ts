import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

export interface ToolPillEntry {
    callId: string;
    name: string;
    label: string;
    args: Record<string, unknown>;
    content: string;
}

@Component({
    selector: 'app-flow-assistant-tool-pill',
    standalone: true,
    imports: [AppSvgIconComponent],
    templateUrl: './flow-assistant-tool-pill.component.html',
    styleUrls: ['./flow-assistant-tool-pill.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowAssistantToolPillComponent {
    // 1. Inputs / Outputs
    readonly tools = input.required<ToolPillEntry[]>();

    // 3. Signals & Computed
    readonly expanded = signal(false);

    // 9. Public methods
    toggle(): void {
        this.expanded.update((v) => !v);
    }

    hasArgs(tool: ToolPillEntry): boolean {
        return Object.keys(tool.args).length > 0;
    }

    formatArgs(args: Record<string, unknown>): string {
        const entries = Object.entries(args);
        if (entries.length === 0) return '';
        return entries.map(([key, value]) => `${key}: ${String(value)}`).join(', ');
    }

    truncateResult(content: string): string {
        const limit = 200;
        if (content.length <= limit) return content;
        return content.slice(0, limit) + '…';
    }
}

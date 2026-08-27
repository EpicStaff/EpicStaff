import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    Finding,
    FindingsMessageData,
    GraphMessage,
    MessageType,
} from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-findings-message',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    templateUrl: './findings-message.component.html',
    styleUrls: ['./findings-message.component.scss'],
    animations: [expandCollapseAnimation],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FindingsMessageComponent {
    @Input() message!: GraphMessage;

    isExpanded = true;

    get data(): FindingsMessageData | null {
        if (this.message?.message_data?.message_type === MessageType.FINDINGS) {
            return this.message.message_data as FindingsMessageData;
        }
        return null;
    }

    toggle(): void {
        this.isExpanded = !this.isExpanded;
    }

    trackByIndex(index: number): number {
        return index;
    }

    severityClass(severity: Finding['severity']): string {
        return `severity-${severity}`;
    }

    fileLocation(finding: Finding): string | null {
        if (!finding.file) return null;
        return finding.line != null ? `${finding.file}:${finding.line}` : finding.file;
    }
}

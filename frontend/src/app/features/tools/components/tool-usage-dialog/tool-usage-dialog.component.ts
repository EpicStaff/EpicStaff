import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';

import { GetToolUsage, InlineUsageItem } from '../../models/tool-config.model';

export interface ToolUsageDialogData {
    toolName: string;
    usage: GetToolUsage;
}

type UsageSectionKey = 'agent' | 'shared' | 'inline';

@Component({
    selector: 'app-tool-usage-dialog',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './tool-usage-dialog.component.html',
    styleUrls: ['./tool-usage-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolUsageDialogComponent {
    private readonly dialogRef = inject<DialogRef<void>>(DialogRef);
    private readonly router = inject(Router);
    private readonly data = inject<ToolUsageDialogData>(DIALOG_DATA);

    public readonly agentSurface = this.data.usage.agent_surface;
    public readonly sharedSurface = this.data.usage.shared_surface;
    public readonly inlineSurface = this.data.usage.inline_surface;

    public readonly agentSurfaceCount = this.agentSurface.length;
    public readonly sharedSurfaceCount = this.sharedSurface.length;
    public readonly inlineSurfaceCount = this.inlineSurface.length;
    public readonly totalCount = this.agentSurfaceCount + this.sharedSurfaceCount + this.inlineSurfaceCount;

    private readonly agentSection = viewChild<ElementRef<HTMLElement>>('agentSection');
    private readonly sharedSection = viewChild<ElementRef<HTMLElement>>('sharedSection');
    private readonly inlineSection = viewChild<ElementRef<HTMLElement>>('inlineSection');

    public readonly hasAny = computed(() => this.totalCount > 0);

    public close(): void {
        this.dialogRef.close();
    }

    public scrollToSection(target: UsageSectionKey): void {
        const el =
            target === 'agent'
                ? this.agentSection()
                : target === 'shared'
                  ? this.sharedSection()
                  : this.inlineSection();
        el?.nativeElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    public openAgentsForSurface(surfaceId: number): void {
        this.openInNewTab(['/agents'], { surfaceId });
    }

    public openFlows(item: InlineUsageItem): void {
        this.openInNewTab([`/flows/${item.id}`], { nodeId: item.node_id });
    }

    private openInNewTab(commands: unknown[], queryParams?: Record<string, unknown>): void {
        const url = this.router.serializeUrl(this.router.createUrlTree(commands, { queryParams }));
        window.open(url, '_blank');
    }
}

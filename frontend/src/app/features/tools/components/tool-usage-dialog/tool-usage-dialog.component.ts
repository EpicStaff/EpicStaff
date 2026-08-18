import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';

import { GetToolUsage } from '../../models/tool-config.model';

export interface ToolUsageDialogData {
    toolName: string;
    usage: GetToolUsage;
}

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

    public readonly agents = this.data.usage.staff;
    public readonly projects = this.data.usage.projects;

    public readonly agentCount = this.agents.length;
    public readonly projectCount = this.projects.length;
    public readonly totalCount = this.agentCount + this.projectCount;

    private readonly agentSection = viewChild<ElementRef<HTMLElement>>('agentSection');
    private readonly projectSection = viewChild<ElementRef<HTMLElement>>('projectSection');

    public readonly hasAny = computed(() => this.totalCount > 0);

    public close(): void {
        this.dialogRef.close();
    }

    public scrollToSection(target: 'agent' | 'project'): void {
        const el = target === 'agent' ? this.agentSection() : this.projectSection();
        el?.nativeElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    public openAgent(): void {
        this.openInNewTab(['/staff']);
    }

    public openProject(id: number): void {
        this.openInNewTab(['/projects', id]);
    }

    private openInNewTab(commands: unknown[]): void {
        const url = this.router.serializeUrl(this.router.createUrlTree(commands));
        window.open(url, '_blank');
    }
}

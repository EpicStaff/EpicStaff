import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ButtonComponent, TabButtonComponent } from '@shared/components';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { CustomToolDialogComponent } from '../../../../user-settings-page/tools/custom-tool-editor/custom-tool-dialog.component';
import { McpToolDialogComponent } from '../../components/mcp-tool-dialog/mcp-tool-dialog.component';
import { GetMcpToolRequest } from '../../models/mcp-tool.model';
import { GetPythonCodeToolRequest } from '../../models/python-code-tool.model';
import { CustomToolsService } from '../../services/custom-tools/custom-tools.service';
import { ToolsEventsService } from '../../services/tools-events.service';
import { ToolsSearchService } from '../../services/tools-search.service';

@Component({
    selector: 'app-tools-list-page',
    standalone: true,
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        TabButtonComponent,
        ButtonComponent,
        FormsModule,
        AppSvgIconComponent,
        HideInlineSubtitleOnOverflowDirective,
    ],
    templateUrl: './tools-list-page.component.html',
    styleUrls: ['./tools-list-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsListPageComponent {
    public tabs = [
        // { label: 'Built-in', link: 'built-in' },
        { label: 'Custom', link: 'custom' },
        { label: 'MCP', link: 'mcp' },
    ];

    public searchTerm: string = '';

    constructor(
        private readonly cdkDialog: Dialog,
        private readonly cdr: ChangeDetectorRef,
        private readonly router: Router,
        private readonly customToolsService: CustomToolsService,
        private readonly toolsEventsService: ToolsEventsService,
        private readonly toolsSearchService: ToolsSearchService
    ) {}

    public get isCustomTabActive(): boolean {
        return this.router.url.includes('/custom');
    }

    public get isMcpTabActive(): boolean {
        return this.router.url.includes('/mcp');
    }

    public get createButtonLabel(): string {
        if (this.isMcpTabActive) {
            return 'Add MCP tool';
        }
        return 'Create custom tool';
    }

    public get createButtonIcon(): string {
        return 'plus';
    }

    public onSearchTermChange(term: string): void {
        this.searchTerm = term;
        this.toolsSearchService.setSearchTerm(term);
    }

    public clearSearch(): void {
        this.searchTerm = '';
        this.toolsSearchService.clearSearch();
    }

    public onCreateToolClick(): void {
        if (this.isMcpTabActive) {
            this.openMcpToolDialog();
        } else {
            this.openCustomToolDialog();
        }
    }

    public openCustomToolDialog(): void {
        this.customToolsService.getPythonCodeTools().subscribe((tools) => {
            const dialogRef = this.cdkDialog.open<GetPythonCodeToolRequest>(CustomToolDialogComponent, {
                data: { pythonTools: tools },
                disableClose: true,
            });

            dialogRef.closed.subscribe((result) => {
                if (result) {
                    // Emit event to notify custom tools component
                    this.toolsEventsService.emitCustomToolCreated(result);
                    this.router.navigate(['/tools/custom']);
                    this.cdr.markForCheck();
                }
            });
        });
    }

    public openMcpToolDialog(): void {
        const dialogRef = this.cdkDialog.open<GetMcpToolRequest>(McpToolDialogComponent, {
            data: {},
            maxWidth: '95vw',
            maxHeight: '90vh',
            autoFocus: true,
        });

        dialogRef.closed.subscribe((result) => {
            if (result) {
                // Emit event to notify MCP tools component
                this.toolsEventsService.emitMcpToolCreated(result);
                this.router.navigate(['/tools/mcp']);
                this.cdr.markForCheck();
            }
        });
    }
}
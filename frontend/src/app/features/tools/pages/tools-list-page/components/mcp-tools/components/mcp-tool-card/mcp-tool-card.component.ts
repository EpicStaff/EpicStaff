import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, Input, Output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

import { AppIconComponent } from '../../../../../../../../shared/components/app-icon/app-icon.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';
import { ToggleSwitchComponent } from '../../../../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { GetMcpToolRequest } from '../../../../../../models/mcp-tool.model';

@Component({
    selector: 'app-mcp-tool-card',
    standalone: true,
    templateUrl: './mcp-tool-card.component.html',
    styleUrls: ['./mcp-tool-card.component.scss'],
    imports: [AppIconComponent, ToggleSwitchComponent, ButtonComponent, MatIconModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class McpToolCardComponent {
    @Input() public tool!: GetMcpToolRequest;
    @Input() public enabled: boolean = false;
    @Input() public starred: boolean = false;
    @Output() public configure = new EventEmitter<GetMcpToolRequest>();
    @Output() public toggle = new EventEmitter<{
        tool: GetMcpToolRequest;
        enabled: boolean;
    }>();
    @Output() public star = new EventEmitter<{
        tool: GetMcpToolRequest;
        starred: boolean;
    }>();
    @Output() public delete = new EventEmitter<GetMcpToolRequest>();

    constructor(private cdr: ChangeDetectorRef) {}

    public get starIcon(): string {
        return this.starred ? 'ui/star-filled' : 'ui/star';
    }

    public onConfigure(): void {
        this.configure.emit(this.tool);
    }

    public onToggle(val: boolean): void {
        this.enabled = val;
        this.toggle.emit({ tool: this.tool, enabled: val });
    }

    public onStar(): void {
        this.starred = !this.starred;
        this.cdr.markForCheck();
        this.star.emit({ tool: this.tool, starred: this.starred });
    }

    public onDelete(): void {
        this.delete.emit(this.tool);
    }
}

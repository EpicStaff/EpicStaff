import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

import { GetMcpToolRequest } from '../../../../../../features/tools/models/mcp-tool.model';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-mcp-tool-item',
    standalone: true,
    imports: [NgClass, AppSvgIconComponent],
    template: `
        <div
            class="mcp-tool-item"
            [ngClass]="{ 'selected-tool': isSelected }"
            (click)="onToolToggle()"
        >
            <app-svg-icon icon="hub" />
            <span class="tool-name">
                {{ tool.name }}
            </span>
            <span class="tool-description">
                {{ tool.tool_name }}
            </span>
            <input
                type="checkbox"
                [checked]="isSelected"
                (click)="onCheckboxClick($event)"
            />
        </div>
    `,
    styleUrls: ['./mcp-tool-item.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class McpToolItemComponent {
    @Input() public tool!: GetMcpToolRequest;
    @Input() public isSelected: boolean = false;

    @Output() public toolToggled = new EventEmitter<GetMcpToolRequest>();

    public onToolToggle(): void {
        this.toolToggled.emit(this.tool);
    }

    public onCheckboxClick(event: Event): void {
        event.stopPropagation();
        this.toolToggled.emit(this.tool);
    }
}

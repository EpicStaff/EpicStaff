import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';
import { ToggleSwitchComponent } from '../../../../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { GetPythonCodeToolRequest } from '../../../../../../models/python-code-tool.model';

@Component({
    selector: 'app-custom-tool-card',
    standalone: true,
    templateUrl: './custom-tool-card.component.html',
    styleUrls: ['./custom-tool-card.component.scss'],
    imports: [AppSvgIconComponent, ToggleSwitchComponent, ButtonComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CustomToolCardComponent {
    @Input() public tool!: GetPythonCodeToolRequest;
    @Input() public enabled: boolean = false;
    @Input() public starred: boolean = false;
    @Output() public configure = new EventEmitter<GetPythonCodeToolRequest>();
    @Output() public toggle = new EventEmitter<{
        tool: GetPythonCodeToolRequest;
        enabled: boolean;
    }>();
    @Output() public star = new EventEmitter<{
        tool: GetPythonCodeToolRequest;
        starred: boolean;
    }>();
    @Output() public delete = new EventEmitter<GetPythonCodeToolRequest>();

    constructor(private cdr: ChangeDetectorRef) {}

    public get starIcon(): string {
        return this.starred ? 'star-filled' : 'star';
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
import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

import { GetPythonCodeToolRequest } from '../../../../../../features/tools/models/python-code-tool.model';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-python-tool-item',
    standalone: true,
    imports: [NgClass, AppSvgIconComponent],
    template: `
        <div class="python-tool-item" [ngClass]="{ 'selected-tool': isSelected }" (click)="onToolToggle()">
            <app-svg-icon icon="python" size="16px" />
            <span class="tool-name">
                {{ tool.name }}
            </span>
            <input type="checkbox" [checked]="isSelected" (click)="onCheckboxClick($event)" />
        </div>
    `,
    styleUrls: ['./python-tool-item.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PythonToolItemComponent {
    @Input() public tool!: GetPythonCodeToolRequest;
    @Input() public isSelected: boolean = false;

    @Output() public toolToggled = new EventEmitter<GetPythonCodeToolRequest>();

    public onToolToggle(): void {
        this.toolToggled.emit(this.tool);
    }

    public onCheckboxClick(event: Event): void {
        event.stopPropagation();
        this.toolToggled.emit(this.tool);
    }
}

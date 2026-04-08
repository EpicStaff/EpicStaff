import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Input } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';

@Component({
    selector: 'app-tool-libraries',
    standalone: true,
    imports: [CommonModule, FormsModule, AppSvgIconComponent, HelpTooltipComponent],
    templateUrl: './tool-libraries.component.html',
    styleUrls: ['./tool-libraries.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolLibrariesComponent {
    private _libraries: string[] = [];

    @Input()
    set libraries(value: string[] | null | undefined) {
        this._libraries = value || [];
    }

    get libraries(): string[] {
        return this._libraries;
    }

    public libraryInput: string = '';

    constructor(private cdr: ChangeDetectorRef) {}

    public addLibrary(): void {
        const lib = this.libraryInput.trim();
        if (lib) {
            this._libraries.push(lib);
            this.libraryInput = '';
            this.cdr.markForCheck();
        }
    }

    public removeLibrary(index: number): void {
        this._libraries.splice(index, 1);
        this.cdr.markForCheck();
    }
}

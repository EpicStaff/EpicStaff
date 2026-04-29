import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-flow-zoom-controls',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    templateUrl: './flow-zoom-controls.component.html',
    styleUrls: ['./flow-zoom-controls.component.scss'],
})
export class FlowZoomControlsComponent {
    @Output() zoomIn = new EventEmitter<void>();
    @Output() zoomOut = new EventEmitter<void>();
    @Output() zoomToFit = new EventEmitter<void>();

    // Zoom controls with their respective tooltips
    readonly zoomControls = [
        {
            icon: 'zoom-in',
            tooltip: 'Zoom In',
            action: () => this.zoomIn.emit(),
        },
        {
            icon: 'zoom-out',
            tooltip: 'Zoom Out',
            action: () => this.zoomOut.emit(),
        },
        {
            icon: 'zoom-scan',
            tooltip: 'Zoom to Fit',
            action: () => this.zoomToFit.emit(),
        },
    ];
}

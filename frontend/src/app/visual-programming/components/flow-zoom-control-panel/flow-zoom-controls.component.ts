import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Output } from '@angular/core';

@Component({
    selector: 'app-flow-zoom-controls',
    standalone: true,
    imports: [CommonModule],
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
            icon: 'ti ti-zoom-in',
            tooltip: 'Zoom In',
            action: () => this.zoomIn.emit(),
        },
        {
            icon: 'ti ti-zoom-out',
            tooltip: 'Zoom Out',
            action: () => this.zoomOut.emit(),
        },
        {
            icon: 'ti ti-zoom-scan',
            tooltip: 'Zoom to Fit',
            action: () => this.zoomToFit.emit(),
        },
    ];
}

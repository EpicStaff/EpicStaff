import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { NoteLinkedRegion } from '../../core/models/node.model';

export interface NoteRegionHighlightData extends NoteLinkedRegion {
    color?: string;
}

export interface NoteRegionResizeStartEvent {
    event: PointerEvent;
    direction: string;
}

@Component({
    selector: 'app-note-region-highlight',
    templateUrl: './note-region-highlight.component.html',
    styleUrls: ['./note-region-highlight.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NoteRegionHighlightComponent {
    readonly region = input.required<NoteRegionHighlightData>();
    readonly resizable = input<boolean>(false);

    readonly resizeStart = output<NoteRegionResizeStartEvent>();
}

import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { expandCollapseAnimation } from '@shared/animations';

import {
    ExtractedChunk,
    ExtractedChunksMessageData,
    GraphMessage,
} from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-extracted-chunks-message',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './extracted-chunks-message.component.html',
    styleUrls: ['./extracted-chunks-message.component.scss'],
    animations: [expandCollapseAnimation],
})
export class ExtractedChunksMessageComponent {
    @Input() message!: GraphMessage;

    isExpanded = true;

    get data(): ExtractedChunksMessageData | null {
        if (this.message?.message_data?.message_type === 'extracted_chunks') {
            return this.message.message_data as ExtractedChunksMessageData;
        }
        return null;
    }

    trackByOrder(_index: number, chunk: ExtractedChunk): number {
        return chunk.chunk_order;
    }

    toggle(): void {
        this.isExpanded = !this.isExpanded;
    }
}

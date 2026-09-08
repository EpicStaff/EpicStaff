import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import {
    ExtractedChunk,
    ExtractedChunksMessageData,
    GraphMessage,
    MessageType,
} from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-extracted-chunks-message',
    imports: [CommonModule, AppSvgIconComponent, CopyButtonComponent],
    templateUrl: './extracted-chunks-message.component.html',
    styleUrls: ['./extracted-chunks-message.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
})
export class ExtractedChunksMessageComponent {
    @Input() message!: GraphMessage;

    isExpanded = true;

    get data(): ExtractedChunksMessageData | null {
        if (this.message?.message_data?.message_type === MessageType.EXTRACTED_CHUNKS) {
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

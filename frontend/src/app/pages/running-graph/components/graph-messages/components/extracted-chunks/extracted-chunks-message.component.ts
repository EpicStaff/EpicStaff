import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { expandCollapseAnimation } from '@shared/animations';

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
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, CopyButtonComponent],
    templateUrl: './extracted-chunks-message.component.html',
    styleUrls: ['./extracted-chunks-message.component.scss'],
    animations: [expandCollapseAnimation],
    changeDetection: ChangeDetectionStrategy.OnPush,
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

    get chunks(): ExtractedChunk[] {
        const data = this.data;
        if (!data) return [];

        if (data.chunks?.length) {
            return data.chunks.map((chunk, index) =>
                typeof chunk === 'string' ? { text: chunk, order: index } : chunk
            );
        }

        if (data.answer !== undefined && data.answer !== null) {
            return [{ text: data.answer, order: 0 }];
        }

        return [];
    }

    trackByOrder(_index: number, chunk: ExtractedChunk): number {
        return chunk.order;
    }

    get ragKind(): 'naive' | 'graph' | null {
        const config = this.data?.rag_search_config;
        if (!config) return null;
        const kind = config.rag_type ?? config.rag_strategy;
        if (kind === 'naive' || kind === 'graph') return kind;
        return 'naive';
    }

    get naiveSearchConfig(): { search_limit: number; similarity_threshold: number } | null {
        const config = this.data?.rag_search_config;
        if (this.ragKind !== 'naive' || !config) return null;
        return {
            search_limit: config.search_limit ?? 0,
            similarity_threshold: config.similarity_threshold ?? 0,
        };
    }

    get graphSearchMethod(): string | null {
        const config = this.data?.rag_search_config;
        if (this.ragKind !== 'graph' || !config) return null;
        return config.search_params?.search_method ?? config.method ?? null;
    }

    get graphMaxContextTokens(): number | null {
        const config = this.data?.rag_search_config;
        if (this.ragKind !== 'graph' || !config) return null;
        return config.search_params?.max_context_tokens ?? config.max_context_tokens ?? null;
    }

    toggle(): void {
        this.isExpanded = !this.isExpanded;
    }
}

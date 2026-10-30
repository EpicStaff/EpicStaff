import { PercentPipe, TitleCasePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, CopyButtonComponent } from '@shared/components';
import { RAG_TYPE_LABELS } from '@shared/constants';
import { formatSmallCostUsd, formatTokens, toFiniteNumber } from '@shared/utils';

import {
    ExtractedChunk,
    ExtractedChunksMessageData,
    ExtractedChunksRagType,
    GraphMessage,
    MessageType,
} from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-extracted-chunks-message',
    imports: [MatTooltip, PercentPipe, TitleCasePipe, AppSvgIconComponent, CopyButtonComponent],
    templateUrl: './extracted-chunks-message.component.html',
    styleUrls: ['./extracted-chunks-message.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExtractedChunksMessageComponent {
    readonly message = input.required<GraphMessage>();

    protected readonly isExpanded = signal(false);

    get data(): ExtractedChunksMessageData | null {
        if (this.message()?.message_data?.message_type === MessageType.EXTRACTED_CHUNKS) {
            return this.message().message_data as ExtractedChunksMessageData;
        }
        return null;
    }

    get ragKind(): ExtractedChunksRagType | null {
        const data = this.data;
        if (!data) return null;
        const kind = data.rag_type ?? data.rag_search_config?.rag_type ?? data.rag_search_config?.rag_strategy;
        return kind === 'naive' || kind === 'graph' ? kind : null;
    }

    get ragTypeLabel(): string | null {
        const kind = this.ragKind;
        return kind ? RAG_TYPE_LABELS[kind] : null;
    }

    get chunks(): ExtractedChunk[] {
        const data = this.data;
        if (!data || this.ragKind === 'graph') return [];
        return (data.chunks ?? []).map((chunk, index) =>
            typeof chunk === 'string' ? { text: chunk, order: index } : chunk
        );
    }

    get chunkCountLabel(): string {
        const count = this.chunks.length;
        return `${count} ${count === 1 ? 'chunk' : 'chunks'}`;
    }

    // Old crew-path graph messages carry the answer as a bare string in chunks[0], with no `answer` field.
    get graphAnswer(): string | null {
        const data = this.data;
        if (!data || this.ragKind !== 'graph') return null;
        if (data.answer != null) return data.answer;
        const legacyAnswer = data.chunks?.[0];
        return typeof legacyAnswer === 'string' ? legacyAnswer : (legacyAnswer?.text ?? '');
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

    protected readonly tokenUsageLabel = computed<string | null>(() => {
        const usage = this.data?.token_usage;
        const tokens = toFiniteNumber(usage?.total_tokens);
        if (!tokens || tokens <= 0) return null;
        const tokensText = `≈ ${formatTokens(tokens)} tokens`;
        const cost = toFiniteNumber(usage?.total_cost_usd);
        return cost && cost > 0 ? `${tokensText} · ${formatSmallCostUsd(cost)}` : tokensText;
    });

    toggle(): void {
        this.isExpanded.update((expanded) => !expanded);
    }
}

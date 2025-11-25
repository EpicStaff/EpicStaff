import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  ExtractedChunk,
  ExtractedChunksMessageData,
  GraphMessage,
} from '../../../../models/graph-session-message.model';
import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';

@Component({
  selector: 'app-extracted-chunks-message',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="extracted-chunks-container" *ngIf="data">
      <div class="header" (click)="toggle()">
        <div class="play-arrow">
          <i
            class="ti"
            [ngClass]="
              isExpanded ? 'ti-caret-down-filled' : 'ti-caret-right-filled'
            "
          ></i>
        </div>
        <div class="icon-container">
          <i class="ti ti-database"></i>
        </div>
        <div class="title">
          <h3>Knowledge Retrieval</h3>
          <p class="subtitle">
            Query:
            <span class="query">
              {{ data.knowledge_query || '—' }}
            </span>
          </p>
        </div>
        <div class="meta">
          <span class="chip">{{ data.chunks.length }} chunks</span>
        </div>
      </div>

      <div
        class="content"
        [class.collapsed]="!isExpanded"
        [@expandCollapse]="isExpanded ? 'expanded' : 'collapsed'"
      >
        <div class="stats">
          <div class="stat">
            <span class="label">Search limit</span>
            <span class="value">{{ data.search_limit }}</span>
          </div>
          <div class="stat">
            <span class="label">Retrieved</span>
            <span class="value">{{ data.retrieved_chunks }}</span>
          </div>
          <div class="stat">
            <span class="label">Similarity threshold</span>
            <span class="value">
              {{ data.similarity_threshold | percent: '1.0-1' }}
            </span>
          </div>
        </div>

        <div class="chunks">
          <article
            class="chunk-card"
            *ngFor="let chunk of data.chunks; trackBy: trackByOrder"
          >
            <div class="chunk-header">
              <div class="chunk-order">#{{ chunk.chunk_order }}</div>
              <div class="chunk-source" [title]="chunk.chunk_source">
                {{ chunk.chunk_source || 'Unknown source' }}
              </div>
              <span class="similarity">
                {{ chunk.chunk_similarity | percent: '1.0-2' }}
              </span>
            </div>
            <pre class="chunk-text">{{ chunk.chunk_text }}</pre>
          </article>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .extracted-chunks-container {
        border-left: 4px solid #5c7cfa;
        border-radius: 8px;
        background: var(--color-nodes-background);
        padding: 1rem;
      
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
      }

      .header {
        display: flex;
        align-items: center;
        cursor: pointer;
        user-select: none;
      }

      .play-arrow {
        margin-right: 16px;
        display: flex;
        align-items: center;
      }

      .play-arrow i {
        color: #5c7cfa;
        font-size: 1.1rem;
        transition: transform 0.3s ease;
      }

      .icon-container {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: #5c7cfa;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 20px;
        flex-shrink: 0;
      }

      .icon-container i {
        font-size: 1.1rem;
        color: var(--gray-900);
      }

      .title h3 {
        margin: 0;
        color: var(--gray-050);
        font-size: 1rem;
        font-weight: 600;
      }

      .subtitle {
        margin: 0;
        color: var(--gray-300);
        font-size: 0.85rem;
      }

      .query {
        color: var(--gray-050);
        font-weight: 500;
      }

      .meta {
        margin-left: auto;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--gray-200);
      }

      .chip {
        background: rgba(92, 124, 250, 0.15);
        color: #bec8ff;
        padding: 0.15rem 0.65rem;
        border-radius: 999px;
        font-size: 0.8rem;
      }

      .content {
        margin-top: 1rem;
        overflow: hidden;
        transition: margin-top 0.2s ease;
      }

      .content.collapsed {
        margin-top: 0;
      }

      .stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 0.75rem;
        margin-bottom: 1rem;
      }

      .stat {
        background: var(--gray-850);
        border-radius: 6px;
        padding: 0.65rem;
      }

      .label {
        display: block;
        font-size: 0.75rem;
        color: var(--gray-400);
      }

      .value {
        font-size: 0.95rem;
        color: var(--gray-050);
        font-weight: 600;
      }

      .chunks {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        max-height: 600px;
        overflow-y: auto;
        overflow-x: hidden;
      }

      .chunk-card {
        background: var(--gray-850);
        border: 1px solid var(--gray-775);
        border-radius: 8px;
        padding: 0.75rem;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
      }

      .chunk-header {
        display: flex;
        align-items: center;
        gap: 0.75rem;
      }

      .chunk-order {
        font-weight: 600;
        color: #5c7cfa;
      }

      .chunk-source {
        color: var(--gray-200);
        font-size: 0.85rem;
        flex: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .similarity {
        font-size: 0.8rem;
        color: var(--gray-300);
      }

      .chunk-text {
        margin: 0;
        font-family: var(--font-family-monospace, 'Fira Code', monospace);
        white-space: pre-wrap;
        color: var(--gray-050);
        background: var(--gray-900);
        border-radius: 6px;
        padding: 0.75rem;
        overflow: visible;
      }
    `,
  ],
  animations: [expandCollapseAnimation],
})
export class ExtractedChunksMessageComponent {
  @Input() message!: GraphMessage;

  isExpanded = true;

  get data(): ExtractedChunksMessageData | null {
    if (
      this.message?.message_data?.message_type === 'extracted_chunks'
    ) {
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


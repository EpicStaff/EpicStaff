import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  GraphMessage,
  MessageType,
  ConditionGroupMessageData,
  ClassificationPromptMessageData,
  ConditionGroupManipulationMessageData,
} from '../../../../models/graph-session-message.model';
import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';

@Component({
  selector: 'app-classification-dt-message',
  standalone: true,
  imports: [CommonModule],
  animations: [expandCollapseAnimation],
  template: `
    <!-- Condition Group -->
    <ng-container *ngIf="isConditionGroup()">
      <div class="dt-flow-container">
        <div class="dt-header" (click)="toggleMessage()">
          <div class="play-arrow">
            <i
              class="ti"
              [ngClass]="
                isMessageExpanded
                  ? 'ti-caret-down-filled'
                  : 'ti-caret-right-filled'
              "
            ></i>
          </div>
          <div class="icon-container" [ngClass]="conditionResultClass()">
            <i class="ti" [ngClass]="conditionResultIcon()"></i>
          </div>
          <div class="header-text">
            <h3>{{ getConditionData()?.group_name }}</h3>
            <span class="badge" [ngClass]="conditionResultClass()">
              {{ getConditionData()?.result ? 'Matched' : 'Not matched' }}
            </span>
          </div>
        </div>

        <div
          class="collapsible-content"
          [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
        >
          <div class="dt-content">
            <div class="detail-row" *ngIf="getConditionData()?.expression">
              <span class="detail-label">Expression</span>
              <code class="detail-value code">{{
                getConditionData()?.expression
              }}</code>
            </div>
            <div class="detail-row" *ngIf="!getConditionData()?.expression">
              <span class="detail-label">Expression</span>
              <span class="detail-value muted">(always true)</span>
            </div>
          </div>
        </div>
      </div>
    </ng-container>

    <!-- Classification Prompt -->
    <ng-container *ngIf="isClassificationPrompt()">
      <div class="dt-flow-container prompt-container">
        <div class="dt-header" (click)="toggleMessage()">
          <div class="play-arrow">
            <i
              class="ti"
              [ngClass]="
                isMessageExpanded
                  ? 'ti-caret-down-filled'
                  : 'ti-caret-right-filled'
              "
            ></i>
          </div>
          <div class="icon-container prompt-icon">
            <i class="ti ti-brain"></i>
          </div>
          <div class="header-text">
            <h3>LLM Classification</h3>
            <span class="badge prompt-badge">{{
              getPromptData()?.prompt_id
            }}</span>
          </div>
        </div>

        <div
          class="collapsible-content"
          [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
        >
          <div class="dt-content">
            <!-- Prompt Text -->
            <div class="detail-section">
              <div
                class="section-heading"
                (click)="toggleSection('prompt'); $event.stopPropagation()"
              >
                <i
                  class="ti"
                  [ngClass]="
                    isPromptExpanded
                      ? 'ti-caret-down-filled'
                      : 'ti-caret-right-filled'
                  "
                ></i>
                Prompt
              </div>
              <div
                class="collapsible-content"
                [@expandCollapse]="
                  isPromptExpanded ? 'expanded' : 'collapsed'
                "
              >
                <pre class="code-block">{{ getPromptData()?.prompt_text }}</pre>
              </div>
            </div>

            <!-- Raw Response -->
            <div class="detail-section">
              <div
                class="section-heading"
                (click)="toggleSection('response'); $event.stopPropagation()"
              >
                <i
                  class="ti"
                  [ngClass]="
                    isResponseExpanded
                      ? 'ti-caret-down-filled'
                      : 'ti-caret-right-filled'
                  "
                ></i>
                Raw Response
              </div>
              <div
                class="collapsible-content"
                [@expandCollapse]="
                  isResponseExpanded ? 'expanded' : 'collapsed'
                "
              >
                <pre class="code-block">{{ getPromptData()?.raw_response }}</pre>
              </div>
            </div>

            <!-- Result Variable -->
            <div class="detail-row">
              <span class="detail-label">Result stored in</span>
              <code class="detail-value code">{{
                getPromptData()?.result_variable
              }}</code>
            </div>

            <!-- Usage -->
            <div class="detail-row" *ngIf="getPromptData()?.usage">
              <span class="detail-label">Tokens</span>
              <span class="detail-value">{{
                getPromptData()?.usage?.['total_tokens'] || 0
              }}</span>
            </div>
          </div>
        </div>
      </div>
    </ng-container>

    <!-- Condition Group Manipulation -->
    <ng-container *ngIf="isManipulation()">
      <div class="dt-flow-container manipulation-container">
        <div class="dt-header" (click)="toggleMessage()">
          <div class="play-arrow">
            <i
              class="ti"
              [ngClass]="
                isMessageExpanded
                  ? 'ti-caret-down-filled'
                  : 'ti-caret-right-filled'
              "
            ></i>
          </div>
          <div class="icon-container manipulation-icon">
            <i class="ti ti-transform"></i>
          </div>
          <div class="header-text">
            <h3>Manipulation</h3>
            <span class="badge manipulation-badge">{{
              getManipulationData()?.group_name
            }}</span>
          </div>
        </div>

        <div
          class="collapsible-content"
          [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
        >
          <div class="dt-content">
            <pre class="code-block">{{
              getManipulationDisplay() | json
            }}</pre>
          </div>
        </div>
      </div>
    </ng-container>
  `,
  styles: [
    `
      .dt-flow-container {
        background-color: var(--color-nodes-background);
        border-radius: 8px;
        padding: 1.25rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        border-left: 4px solid #a78bfa;
      }

      .prompt-container {
        border-left-color: #f59e0b;
      }

      .manipulation-container {
        border-left-color: #6ee7b7;
      }

      .dt-header {
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
        color: #a78bfa;
        font-size: 1.1rem;
        transition: transform 0.3s ease;
      }

      .prompt-container .play-arrow i {
        color: #f59e0b;
      }

      .manipulation-container .play-arrow i {
        color: #6ee7b7;
      }

      .icon-container {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background-color: #a78bfa;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 16px;
        flex-shrink: 0;
      }

      .icon-container i {
        color: var(--gray-900);
        font-size: 1.25rem;
      }

      .icon-container.matched {
        background-color: #34d399;
      }

      .icon-container.not-matched {
        background-color: #6b7280;
      }

      .prompt-icon {
        background-color: #f59e0b;
      }

      .manipulation-icon {
        background-color: #6ee7b7;
      }

      .header-text {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
      }

      h3 {
        color: var(--gray-100);
        font-size: 1.1rem;
        font-weight: 600;
        margin: 0;
      }

      .badge {
        font-size: 0.75rem;
        padding: 2px 10px;
        border-radius: 12px;
        font-weight: 500;
      }

      .badge.matched {
        background-color: rgba(52, 211, 153, 0.15);
        color: #34d399;
      }

      .badge.not-matched {
        background-color: rgba(107, 114, 128, 0.15);
        color: #9ca3af;
      }

      .prompt-badge {
        background-color: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
      }

      .manipulation-badge {
        background-color: rgba(110, 231, 183, 0.15);
        color: #6ee7b7;
      }

      .dt-content {
        padding-left: 5.5rem;
        margin-top: 1rem;
        overflow: hidden;
      }

      .detail-row {
        display: flex;
        align-items: baseline;
        gap: 12px;
        margin-bottom: 0.5rem;
      }

      .detail-label {
        color: var(--gray-400);
        font-size: 0.85rem;
        font-weight: 500;
        min-width: 120px;
        flex-shrink: 0;
      }

      .detail-value {
        color: var(--gray-200);
        font-size: 0.9rem;
      }

      .detail-value.code {
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        background-color: var(--gray-800);
        padding: 2px 8px;
        border-radius: 4px;
        border: 1px solid var(--gray-750);
      }

      .detail-value.muted {
        color: var(--gray-500);
        font-style: italic;
      }

      .detail-section {
        margin-bottom: 0.75rem;
      }

      .section-heading {
        font-weight: 500;
        color: var(--gray-300);
        margin-bottom: 0.5rem;
        cursor: pointer;
        user-select: none;
        display: flex;
        align-items: center;
      }

      .section-heading i {
        margin-right: 8px;
        color: #f59e0b;
        font-size: 1.1rem;
        margin-left: -3px;
        transition: transform 0.3s ease;
      }

      .code-block {
        background-color: var(--gray-800);
        border: 1px solid var(--gray-750);
        border-radius: 8px;
        padding: 1rem;
        color: var(--gray-200);
        white-space: pre-wrap;
        word-break: break-word;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 0.85rem;
        margin: 0 0 0 23px;
        max-height: 300px;
        overflow-y: auto;
      }

      .collapsible-content {
        overflow: hidden;
        position: relative;
      }

      .collapsible-content.ng-animating {
        overflow: hidden;
      }
    `,
  ],
})
export class ClassificationDtMessageComponent {
  @Input() message!: GraphMessage;

  isMessageExpanded = false;
  isPromptExpanded = true;
  isResponseExpanded = true;

  isConditionGroup(): boolean {
    return (
      this.message.message_data?.message_type === MessageType.CONDITION_GROUP
    );
  }

  isClassificationPrompt(): boolean {
    return (
      this.message.message_data?.message_type ===
      MessageType.CLASSIFICATION_PROMPT
    );
  }

  isManipulation(): boolean {
    return (
      this.message.message_data?.message_type ===
      MessageType.CONDITION_GROUP_MANIPULATION
    );
  }

  getConditionData(): ConditionGroupMessageData | null {
    if (this.isConditionGroup()) {
      return this.message.message_data as ConditionGroupMessageData;
    }
    return null;
  }

  getPromptData(): ClassificationPromptMessageData | null {
    if (this.isClassificationPrompt()) {
      return this.message.message_data as ClassificationPromptMessageData;
    }
    return null;
  }

  getManipulationData(): ConditionGroupManipulationMessageData | null {
    if (this.isManipulation()) {
      return this.message.message_data as ConditionGroupManipulationMessageData;
    }
    return null;
  }

  getManipulationDisplay(): Record<string, any> | null {
    const data = this.getManipulationData();
    if (!data) return null;
    // Show only changed variables; fall back to full state for old messages
    if (data.changed_variables && Object.keys(data.changed_variables).length > 0) {
      return data.changed_variables;
    }
    return data.state?.['variables'] ?? data.state;
  }

  conditionResultClass(): string {
    return this.getConditionData()?.result ? 'matched' : 'not-matched';
  }

  conditionResultIcon(): string {
    return this.getConditionData()?.result ? 'ti-check' : 'ti-x';
  }

  toggleMessage(): void {
    this.isMessageExpanded = !this.isMessageExpanded;
  }

  toggleSection(section: 'prompt' | 'response'): void {
    if (section === 'prompt') {
      this.isPromptExpanded = !this.isPromptExpanded;
    } else if (section === 'response') {
      this.isResponseExpanded = !this.isResponseExpanded;
    }
  }
}

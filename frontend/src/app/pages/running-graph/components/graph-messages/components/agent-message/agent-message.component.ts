import { Component, Input, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GraphMessage } from '../../../../models/graph-session-message.model';
import { NgxJsonViewerModule } from 'ngx-json-viewer';
import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { GetAgentRequest } from '../../../../../../shared/models/agent.model';

@Component({
  selector: 'app-agent-message',
  standalone: true,
  imports: [CommonModule, NgxJsonViewerModule],
  animations: [expandCollapseAnimation],
  template: `
    <div class="agent-flow-container">
      <!-- Agent Message Header with Toggle -->
      <div class="agent-header" (click)="toggleMessage()">
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
        <div class="icon-container">
          <i class="ti ti-robot"></i>
        </div>
        <div class="header-text">
          Agent <span class="agent-name">{{ getAgentName() }}</span> used tool
          <span class="tool-name-header">{{ getTool() }}</span>
        </div>
      </div>

      <!-- Collapsible Agent Content -->
      <div
        class="collapsible-content"
        [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
      >
        <div class="agent-content">
          <!-- Thought Section -->
          <div class="thought-container" *ngIf="hasThought()">
            <div class="section-heading" (click)="toggleSection('thought')">
              <i
                class="ti"
                [ngClass]="
                  isThoughtExpanded
                    ? 'ti-caret-down-filled'
                    : 'ti-caret-right-filled'
                "
              ></i>
              Thought
            </div>
            <div
              class="collapsible-content"
              [@expandCollapse]="isThoughtExpanded ? 'expanded' : 'collapsed'"
            >
              <div class="thought-bubble">
                <span class="thought-quote">"</span
                >{{ cleanThought(getThought())
                }}<span class="thought-quote">"</span>
              </div>
            </div>
          </div>

          <!-- Tool Section -->
          <div class="tool-container" *ngIf="hasTool()">
            <div class="section-heading" (click)="toggleSection('tool')">
              <i
                class="ti"
                [ngClass]="
                  isToolExpanded
                    ? 'ti-caret-down-filled'
                    : 'ti-caret-right-filled'
                "
              ></i>
              Tool
            </div>
            <div
              class="collapsible-content"
              [@expandCollapse]="isToolExpanded ? 'expanded' : 'collapsed'"
            >
              <div class="tool-wrapper">
                <div class="tool-name">{{ getTool() }}</div>
                <div class="tool-input-container" *ngIf="hasToolInput()">
                  <ngx-json-viewer
                    *ngIf="isValidJson(getToolInput())"
                    [json]="getParsedJson('tool')"
                    [expanded]="false"
                  ></ngx-json-viewer>
                  <div
                    class="code-content"
                    *ngIf="!isValidJson(getToolInput())"
                  >
                    {{ formatJson(getToolInput()) }}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Tool Output Section at same level as Thought and Tool -->
          <div class="result-container" *ngIf="getResult()">
            <div class="section-heading" (click)="toggleSection('result')">
              <i
                class="ti"
                [ngClass]="
                  isResultExpanded
                    ? 'ti-caret-down-filled'
                    : 'ti-caret-right-filled'
                "
              ></i>
              Tool Output
            </div>
            <div
              class="collapsible-content"
              [@expandCollapse]="isResultExpanded ? 'expanded' : 'collapsed'"
            >
              <div class="result-content">
                <ngx-json-viewer
                  *ngIf="isValidJson(getResult())"
                  [json]="getParsedJson('result')"
                  [expanded]="true"
                ></ngx-json-viewer>
                <div
                  class="formatted-content"
                  *ngIf="!isValidJson(getResult())"
                >
                  {{ getResult() }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }

    .agent-flow-container {
        background-color: var(--color-nodes-background); 
      border-radius: 8px;
      padding: 1.25rem;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      border-left: 4px solid #8e5cd9;
    }

    .agent-header {
      display: flex;
      align-items: center;
      cursor: pointer;
      user-select: none;
    }

    .play-arrow {
      margin-right: 16px;
      display: flex;
      align-items: center;

      i {
        color: #8e5cd9;
        font-size: 1.1rem;
        transition: transform 0.3s ease;
      }
    }

    .icon-container {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background-color: #8e5cd9;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-right: 20px;
      flex-shrink: 0;

      i {
        color: var(--gray-900);
        font-size: 1.25rem;
      }
    }

    .header-text {
      flex: 1;
      color: var(--gray-100);
      font-size: 1.1rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .agent-name {
      color: #8e5cd9;
      font-weight: 600;
    }

    .tool-name-header {
      color: #8e5cd9;
      font-weight: 400;
    }

    .agent-content {
      display: flex;
      flex-direction: column;
      gap: 1rem;
      padding-left: 5.5rem;
      margin-top: 1.25rem;
      overflow: hidden;
    }

    /* Collapsible content container */
    .collapsible-content {
      overflow: hidden;
      position: relative;

      &.ng-animating {
        overflow: hidden;
      }
    }

    .section-heading {
      font-weight: 500;
      color: var(--gray-300);
      margin-bottom: 0.5rem;
      cursor: pointer;
      user-select: none;
      display: flex;
      align-items: center;

      i {
        margin-right: 8px;
        color: #8e5cd9;
        font-size: 1.1rem;
        margin-left: -3px;
        transition: transform 0.3s ease;
      }
    }

    .thought-bubble {
      background-color: var(--gray-800);
      border: 1px solid var(--gray-750);
      border-radius: 8px;
      padding: 1rem;
      position: relative;
      color: var(--gray-200);
      font-style: italic;
      margin-left: 23px;
    }

    .thought-quote {
      color: #8e5cd9;
      font-size: 1.5rem;
      font-weight: bold;
      vertical-align: sub;
      line-height: 0;
    }

    .tool-wrapper {
      margin-left: 23px;
    }

    .tool-name {
      font-weight: 600;
      color: #8e5cd9;
      margin-bottom: 0.5rem;
    }

    .tool-input-container {
      background-color: var(--gray-800);
      border: 1px solid var(--gray-750);
      border-radius: 8px;
      padding: 1rem;
      overflow: auto;
      max-height: 400px;
      padding-inline: 3px;
    }

    .input-label {
      font-weight: 500;
      color: var(--gray-300);
      margin-bottom: 0.5rem;
    }

    .formatted-content {
      font-size: 0.85rem;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--gray-200);
      max-height: 400px;
      overflow-y: auto;
    }

    /* Tool Output Styling */
    .result-container {
      /* Remove margin to align with other sections */
    }

    .result-content {
        background-color: var(--gray-850);
      border: 1px solid var(--gray-750);
      border-radius: 8px;
      padding: 1rem;
      color: #e3e3e3;
      word-break: break-word;
      overflow-y: auto;
      max-height: 400px;
      white-space: pre-wrap;
      margin-left: 23px;
    }

    .code-content {
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--gray-200);
      font-size: 0.85rem;
      max-height: 400px;
      overflow-y: auto;
    }
  `,
})
export class AgentMessageComponent implements OnInit {
  @Input() public message!: GraphMessage;
  @Input() public agent: GetAgentRequest | null = null; // Add input for agent data

  private toolJsonData: any = null;
  private resultJsonData: any = null;

  public isMessageExpanded = false;
  public isThoughtExpanded = true;
  public isToolExpanded = true;
  public isResultExpanded = false;

  public ngOnInit(): void {
    if (this.hasToolInput()) {
      this.tryParseToolJson();
    }

    if (this.getResult()) {
      this.tryParseResultJson();
    }
  }

  public toggleMessage(): void {
    this.isMessageExpanded = !this.isMessageExpanded;
  }

  public toggleSection(section: 'thought' | 'tool' | 'result'): void {
    if (section === 'thought') {
      this.isThoughtExpanded = !this.isThoughtExpanded;
    } else if (section === 'tool') {
      this.isToolExpanded = !this.isToolExpanded;
    } else if (section === 'result') {
      this.isResultExpanded = !this.isResultExpanded;
    }
  }

  public getAgentName(): string {
    // If we have the agent data, use the agent's role
    if (this.agent && this.agent.role) {
      // Limit agent name to 50 characters
      const name = this.agent.role;
      return name.length > 50 ? name.substring(0, 50) + '...' : name;
    }

    // Fall back to the previous implementation
    if (!this.message.message_data) return 'Agent';

    if (
      this.message.message_data.message_type === 'agent' &&
      'agent_id' in this.message.message_data
    ) {
      return `Agent #${String(this.message.message_data.agent_id)}`;
    }

    return 'Agent';
  }

  public getAgentId(): string {
    if (!this.message.message_data) return 'Unknown';

    if (
      this.message.message_data.message_type === 'agent' &&
      'agent_id' in this.message.message_data
    ) {
      return String(this.message.message_data.agent_id);
    }

    return 'Unknown';
  }

  public getProjectId(): string {
    if (!this.message.message_data) return 'Unknown';

    if (
      this.message.message_data.message_type === 'agent' &&
      'crew_id' in this.message.message_data
    ) {
      return String(this.message.message_data.crew_id);
    }

    return 'Unknown';
  }

  public hasThought(): boolean {
    if (!this.message.message_data) return false;

    return (
      this.message.message_data.message_type === 'agent' &&
      'thought' in this.message.message_data &&
      !!this.message.message_data.thought
    );
  }

  public getThought(): string {
    if (!this.hasThought()) return '';
    return (this.message.message_data as any).thought;
  }

  public cleanThought(thought: string): string {
    // Remove markdown code block syntax if present
    return thought
      .replace(/```[\s\S]*?```/g, '')
      .replace(/^```/, '')
      .replace(/```$/, '')
      .replace(/^Thought: /g, '') // Use global flag to remove all occurrences
      .replace(/Thought: /g, '') // Remove any other occurrences
      .trim();
  }

  public hasTool(): boolean {
    if (!this.message.message_data) return false;

    return (
      this.message.message_data.message_type === 'agent' &&
      'tool' in this.message.message_data &&
      !!this.message.message_data.tool
    );
  }

  public getTool(): string {
    if (!this.hasTool()) return '';
    return (this.message.message_data as any).tool;
  }

  public hasToolInput(): boolean {
    if (!this.message.message_data) return false;

    return (
      this.message.message_data.message_type === 'agent' &&
      'tool_input' in this.message.message_data &&
      !!this.message.message_data.tool_input
    );
  }

  public getToolInput(): string {
    if (!this.hasToolInput()) return '';
    return (this.message.message_data as any).tool_input;
  }

  private tryParseToolJson(): void {
    if (this.hasToolInput()) {
      try {
        this.toolJsonData = JSON.parse(this.getToolInput());
      } catch (e) {
        this.toolJsonData = null;
      }
    }
  }

  private tryParseResultJson(): void {
    if (this.getResult()) {
      try {
        this.resultJsonData = JSON.parse(this.getResult());
      } catch (e) {
        this.resultJsonData = null;
      }
    }
  }

  public isValidJson(str: string): boolean {
    try {
      JSON.parse(str);
      return true;
    } catch (e) {
      return false;
    }
  }

  public getParsedJson(type: 'tool' | 'result'): any {
    if (type === 'tool') {
      if (this.toolJsonData === null) {
        this.tryParseToolJson();
      }
      return this.toolJsonData;
    } else {
      if (this.resultJsonData === null) {
        this.tryParseResultJson();
      }
      return this.resultJsonData;
    }
  }

  public formatJson(jsonString: string): string {
    try {
      const parsed = JSON.parse(jsonString);
      // Using more explicit formatting to ensure proper indentation and brackets
      let formatted = JSON.stringify(parsed, null, 2);
      return formatted;
    } catch (e) {
      return jsonString;
    }
  }

  public getResult(): string {
    if (!this.message.message_data) return '';
    return (this.message.message_data as any).result?.trim() || '';
  }
}

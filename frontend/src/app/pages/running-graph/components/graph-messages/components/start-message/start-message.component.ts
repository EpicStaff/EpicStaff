import { Component, Input, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GraphMessage } from '../../../../models/graph-session-message.model';
import { NgxJsonViewerModule } from 'ngx-json-viewer';
import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';

@Component({
  selector: 'app-start-message',
  standalone: true,
  imports: [CommonModule, NgxJsonViewerModule],
  encapsulation: ViewEncapsulation.Emulated,
  animations: [expandCollapseAnimation],
  template: `
    <div class="start-container">
      <div class="start-header" (click)="toggleMessage()">
        <div class="play-arrow" *ngIf="hasInputs()">
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
          <i class="ti ti-flag"></i>
        </div>
        <h3>
          <span class="node-name">{{ message.name }}</span> started
        </h3>
      </div>

      <!-- Collapsible Content -->
      <div
        class="collapsible-content"
        [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
      >
        <div class="start-content">
          <!-- Input Parameters Section -->
          <div class="input-container" *ngIf="hasInputs()">
            <div class="section-heading" (click)="toggleInputs($event)">
              <i
                class="ti"
                [ngClass]="
                  isInputsExpanded
                    ? 'ti-caret-down-filled'
                    : 'ti-caret-right-filled'
                "
              ></i>
              Input Parameters
            </div>
            <div
              class="collapsible-content"
              [@expandCollapse]="isInputsExpanded ? 'expanded' : 'collapsed'"
            >
              <div class="input-content">
                <ngx-json-viewer
                  [json]="getStartInput()"
                  [expanded]="false"
                ></ngx-json-viewer>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .start-container {
        position: relative;
        background-color: var(--color-nodes-background);
        border-radius: 8px;
        padding: 1.25rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        border-left: 4px solid #d29922;
      }

      .start-header {
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
        color: #d29922;
        font-size: 1.1rem;
        transition: transform 0.3s ease;
      }

      .icon-container {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background-color: #d29922;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 20px;
        flex-shrink: 0;
      }

      .icon-container i {
        color: var(--gray-900);
        font-size: 1.25rem;
      }

      h3 {
        color: var(--gray-100);
        font-size: 1.1rem;
        font-weight: 600;
        margin: 0;
      }

      .node-name {
        color: #d29922;
        font-weight: 400;
      }

      /* Collapsible content container */
      .collapsible-content {
        overflow: hidden;
        position: relative;
      }

      .collapsible-content.ng-animating {
        overflow: hidden;
      }

      .start-content {
        display: flex;
        flex-direction: column;
        gap: 1rem;
        padding-left: 5.5rem;
        margin-top: 1.25rem;
      }

      /* Section styling */
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
        color: #d29922;
        font-size: 1.1rem;
        margin-left: -3px;
        transition: transform 0.3s ease;
      }

      .input-container {
        margin-bottom: 0.5rem;
      }

      .input-content {
        background-color: var(--gray-800);
        border: 1px solid var(--gray-750);
        border-radius: 8px;
        padding: 1rem;
        overflow: auto;
        max-height: 400px;
        margin-left: 23px;
      }
    `,
  ],
})
export class StartMessageComponent {
  @Input() message!: GraphMessage;
  isMessageExpanded = false;
  isInputsExpanded = true;

  toggleMessage(): void {
    if (!this.hasInputs()) return;
    this.isMessageExpanded = !this.isMessageExpanded;
  }

  toggleInputs(event: Event): void {
    // Stop the click event from propagating to parent elements
    event.stopPropagation();
    this.isInputsExpanded = !this.isInputsExpanded;
  }

  hasInputs(): boolean {
    const input = this.getStartInput();
    return input && Object.keys(input).length > 0;
  }

  getStartInput(): any {
    if (!this.message.message_data) return {};

    if (
      this.message.message_data.message_type === 'start' &&
      'input' in this.message.message_data
    ) {
      return this.message.message_data.input;
    }

    return {};
  }
}

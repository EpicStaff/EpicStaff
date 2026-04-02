import { animate, state, style, transition, trigger } from '@angular/animations';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

@Component({
    selector: 'app-chats-header',
    standalone: true,
    imports: [CommonModule, FormsModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    animations: [
        trigger('modelSwitch', [
            state(
                'mini',
                style({
                    transform: 'translateX(0)',
                })
            ),
            state(
                'full',
                style({
                    transform: 'translateX(100%)',
                })
            ),
            transition('mini <=> full', [animate('0.3s ease-in-out')]),
        ]),
    ],
    template: `
        <div class="header">
            <div class="title-container">
                <h1 class="title">{{ headerTitle }}</h1>
            </div>
        </div>
    `,
    styles: [
        `
            .header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                height: 4.3rem !important;
                width: 100%;
                padding: 1rem 3rem;
                border-bottom: 1px solid var(--color-divider-subtle);
            }
            .title-container {
                display: flex;
                align-items: center;
            }
            .title {
                font-size: 24px;
                font-weight: 400;
                letter-spacing: -0.02em;
                line-height: 1.2;
                color: var(--white);
                padding: 0;
                margin: 0;
            }
            .header-actions {
                display: flex;
                align-items: center;
                gap: 24px;
            }
            .api-key-container {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .save-button {
                padding: 8px 12px;
                border: none;
                background-color: var(--accent-color);
                color: var(--white);
                border-radius: 6px;
                cursor: pointer;
                font-size: 14px;
            }
            .error-message {
                color: red;
                font-size: 12px;
            }
            .input-with-toggle {
                position: relative;
                display: flex;
                align-items: center;
            }
            .input-with-toggle input {
                padding: 8px 36px 8px 12px;
                border-radius: 6px;
                border: 1px solid var(--gray-600);
                background-color: rgba(255, 255, 255, 0.05);
                color: var(--white);
                width: 240px;
                height: 38px;
                font-size: 14px;
                transition: all 0.2s ease;
            }
            .input-with-toggle input:focus {
                outline: none;
                border-color: var(--accent-color);
                box-shadow: 0 0 0 1px rgba(var(--accent-color-rgb), 0.2);
            }
            .input-with-toggle input::placeholder {
                color: var(--gray-400);
            }
            .toggle-visibility {
                position: absolute;
                right: 8px;
                background: none;
                border: none;
                cursor: pointer;
                color: var(--gray-400);
                display: flex;
                align-items: center;
                justify-content: center;
                transition: color 0.2s ease;
            }
            .toggle-visibility:hover {
                color: var(--white);
            }
            .ti {
                font-size: 18px;
            }
            .model-switcher {
                position: relative;
                display: flex;
                background-color: rgba(255, 255, 255, 0.05);
                border-radius: 6px;
                padding: 3px;
                border: 1px solid var(--gray-600);
                overflow: hidden;
            }
            .model-options {
                display: flex;
                width: 100%;
                position: relative;
                z-index: 2;
            }
            .model-button {
                background: none;
                border: none;
                color: var(--gray-300);
                padding: 6px 12px;
                font-size: 14px;
                border-radius: 4px;
                cursor: pointer;
                transition: all 0.2s ease;
                z-index: 2;
                width: 100px;
                white-space: nowrap;
            }
            .model-button.active {
                color: white;
                font-weight: 500;
            }
            .model-button:not(.active):hover {
                color: var(--white);
            }
            .slider-indicator {
                position: absolute;
                top: 3px;
                left: 3px;
                width: calc(50% - 3px);
                height: calc(100% - 6px);
                background-color: var(--accent-color);
                border-radius: 4px;
                z-index: 1;
                transform: translateX(0);
            }
        `,
    ],
})
export class ChatsHeaderComponent implements OnInit {
    @Input() headerTitle: string = 'Chats';

    constructor() {}

    ngOnInit(): void {}
}

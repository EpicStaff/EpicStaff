// no-messages.component.ts
import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';

@Component({
    selector: 'app-no-messages',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="no-messages">
            <div class="no-messages-content">
                <i class="ti ti-message-circle-off"></i>
                <p>No messages available for this session.</p>
            </div>
        </div>
    `,
    styles: [
        `
            .no-messages {
                display: flex;
                align-items: center;
                justify-content: center;
                width: 100%;
                min-height: 300px;
                padding: 2rem;
                animation: fadeIn 0.3s ease-out;

                .no-messages-content {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    gap: 0.5rem;

                    i {
                        font-size: 1.5rem;
                        color: var(--gray-400);
                    }

                    p {
                        color: var(--gray-400);
                        font-size: 0.95rem;
                        font-weight: 500;
                        margin: 0;
                    }
                }
            }

            @keyframes fadeIn {
                from {
                    opacity: 0;
                    transform: translateY(10px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }
        `,
    ],
})
export class NoMessagesComponent {}

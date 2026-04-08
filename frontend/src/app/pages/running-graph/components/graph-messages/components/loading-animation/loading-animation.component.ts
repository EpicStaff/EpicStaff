import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit } from '@angular/core';

@Component({
    selector: 'app-loading-dots',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="processing-indicator">
            <div class="dots-container">
                <div class="dot"></div>
                <div class="dot"></div>
                <div class="dot"></div>
            </div>
            <div class="processing-text">{{ currentText }}</div>
        </div>
    `,
    styles: [
        `
            .processing-indicator {
                display: flex;
                width: fit-content;
                padding: 10px;
                margin: 0 auto;
                margin-bottom: 2rem;
            }

            .dots-container {
                display: flex;
                align-items: center;
                margin-right: 8px;
            }

            .dot {
                width: 6px;
                height: 6px;
                margin: 0 3px;
                background-color: #666;
                border-radius: 50%;
                animation: bounce 1.4s infinite ease-in-out both;
            }

            .dot:nth-child(1) {
                animation-delay: -0.32s;
            }

            .dot:nth-child(2) {
                animation-delay: -0.16s;
            }

            .processing-text {
                font-size: 14px;
                color: #666;
                min-width: 100px;
                text-align: center;
                transition: opacity 0.3s ease;
                animation: fadeText 4s infinite ease-in-out;
            }

            @keyframes bounce {
                0%,
                80%,
                100% {
                    transform: scale(0);
                    opacity: 0.3;
                }
                40% {
                    transform: scale(1);
                    opacity: 1;
                }
            }

            @keyframes fadeText {
                0%,
                100% {
                    opacity: 0.7;
                }
                50% {
                    opacity: 1;
                }
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.Default,
})
export class LoadingDotsComponent implements OnInit, OnDestroy {
    private processingTexts = ['Processing', 'Executing', 'Running', 'Computing'];

    currentText = this.processingTexts[0];
    private textIndex = 0;
    private textUpdateInterval: ReturnType<typeof setInterval> | undefined;

    ngOnInit() {
        // Rotate through different text messages every 1 second
        this.textUpdateInterval = setInterval(() => {
            // Always increment and wrap around
            this.textIndex = (this.textIndex + 1) % this.processingTexts.length;

            // Explicitly set the current text
            this.currentText = this.processingTexts[this.textIndex];
        }, 1000);
    }

    ngOnDestroy() {
        if (this.textUpdateInterval) {
            clearInterval(this.textUpdateInterval);
        }
    }
}

// voice-visualizer.component.ts
import { CommonModule } from '@angular/common';
import { Component, ElementRef, inject, OnDestroy, OnInit, ViewChild } from '@angular/core';

import { WavRecorderService } from '../../../../../services/wav-recorder.service';

@Component({
    selector: 'app-voice-visualizer',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="visualizer">
            <div class="wave-container">
                <canvas #canvas width="300" height="40"></canvas>
            </div>
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                width: fit-content;
            }

            .visualizer {
                display: flex;
                align-items: center;
                border-radius: 8px;
                width: 100%;
            }

            .wave-container {
                flex: 1;
                display: flex;
                align-items: center;
                width: 100%;
                height: 100%;

                canvas {
                    width: 100%;
                    height: 40px;
                    background-color: var(--gray-800);
                    border-radius: 8px;
                    display: block;
                    border: 1px solid var(--gray-750);
                }
            }
        `,
    ],
})
export class VoiceVisualizerComponent implements OnInit, OnDestroy {
    @ViewChild('canvas', { static: true })
    canvasRef!: ElementRef<HTMLCanvasElement>;

    private animationFrameId: number | null = null;
    private wavRecorderService = inject(WavRecorderService);

    ngOnInit(): void {
        this.startVisualization();
    }

    private startVisualization() {
        if (!this.wavRecorderService.isRecording()) {
            return;
        }
        const canvas = this.canvasRef.nativeElement;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            return;
        }

        const draw = () => {
            try {
                const analysis = this.wavRecorderService.getFrequencyData('voice', -100, -30);
                const values = analysis.values;
                const barCount = values.length;

                ctx.clearRect(0, 0, canvas.width, canvas.height);

                // Scale factor to reduce overall bar height
                const amplitudeScale = 0.5;
                const barWidth = canvas.width / barCount;

                // Fill background with a gradient
                const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
                gradient.addColorStop(0, 'rgba(104, 95, 255, 0.1)');
                gradient.addColorStop(1, 'rgba(104, 95, 255, 0.05)');
                ctx.fillStyle = gradient;
                ctx.fillRect(0, 0, canvas.width, canvas.height);

                // Draw bars
                for (let i = 0; i < barCount; i++) {
                    const amplitude = values[i] * amplitudeScale;
                    const barHeight = amplitude * canvas.height;
                    const x = i * barWidth;

                    // Calculate a position-based color for the bars
                    const barGradient = ctx.createLinearGradient(0, canvas.height, 0, canvas.height - barHeight);
                    barGradient.addColorStop(0, 'rgba(104, 95, 255, 0.8)');
                    barGradient.addColorStop(1, 'rgba(104, 95, 255, 0.4)');

                    ctx.fillStyle = barGradient;

                    // Draw rounded bars
                    const barWidthWithGap = barWidth * 0.7; // Make bars slightly narrower for gaps
                    const barX = x + (barWidth - barWidthWithGap) / 2;

                    ctx.beginPath();
                    ctx.roundRect(
                        barX,
                        canvas.height - barHeight,
                        barWidthWithGap,
                        barHeight,
                        [2, 2, 0, 0] // Rounded corners only at the top
                    );
                    ctx.fill();
                }
            } catch (error) {
                console.error('Error retrieving frequency data:', error);
            }
            this.animationFrameId = requestAnimationFrame(draw);
        };

        draw();
    }

    ngOnDestroy(): void {
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
        }
    }
}

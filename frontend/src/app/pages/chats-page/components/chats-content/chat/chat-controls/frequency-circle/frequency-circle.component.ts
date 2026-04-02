import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';

import { ConsoleService } from '../../../../../services/console.service';

interface AudioAnalysisOutputType {
    values: Float32Array | number[]; // amplitude data in [0..1]
}

@Component({
    selector: 'app-tiny-audio-visualizer',
    standalone: true,
    imports: [CommonModule],
    template: `<canvas #canvas width="20" height="20"></canvas>`,
    styles: [
        `
            :host {
                display: inline-block;
                width: 20px;
                height: 20px;
            }
            canvas {
                width: 20px;
                height: 20px;
                border-radius: 50%;
                display: block;
            }
        `,
    ],
})
export class TinyAudioVisualizerComponent implements OnInit, OnDestroy {
    @ViewChild('canvas', { static: true })
    canvasRef!: ElementRef<HTMLCanvasElement>;

    private animationFrameId: number | null = null;
    private time = 0;

    constructor(private consoleService: ConsoleService) {}

    ngOnInit(): void {
        this.startAnimation();
    }

    private startAnimation(): void {
        const canvas = this.canvasRef.nativeElement;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const renderFrame = () => {
            // Clear the canvas
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Get frequency data
            const analysis = this.consoleService.getStreamFrequencyData('voice', -100, -30) as AudioAnalysisOutputType;

            // Default amplitude if no data
            let avgAmplitude = 0;

            // Calculate average amplitude if we have data
            if (analysis && analysis.values && analysis.values.length > 0) {
                let sum = 0;
                for (let i = 0; i < analysis.values.length; i++) {
                    sum += analysis.values[i];
                }
                avgAmplitude = sum / analysis.values.length;
            }

            // Set up center and radius
            const centerX = canvas.width / 2;
            const centerY = canvas.height / 2;
            const radius = Math.min(centerX, centerY);

            // Create pulsing gradient based on audio amplitude
            const pulseSize = 0.5 + avgAmplitude * 0.5;

            // Create gradient with accent blue colors only
            const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);

            // Use accent blue colors with varying brightness and opacity based on amplitude
            const alpha = 0.5 + avgAmplitude * 0.5;

            gradient.addColorStop(0, `rgba(104, 95, 255, ${alpha})`);
            gradient.addColorStop(pulseSize, `rgba(65, 58, 235, ${alpha * 0.7})`);
            gradient.addColorStop(1, `rgba(45, 40, 190, ${alpha * 0.3})`);

            // Draw circle with gradient
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
            ctx.fillStyle = gradient;
            ctx.fill();

            // Increase time for animation
            this.time++;

            // Schedule next frame
            this.animationFrameId = requestAnimationFrame(renderFrame);
        };

        renderFrame();
    }

    ngOnDestroy(): void {
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
        }
    }
}

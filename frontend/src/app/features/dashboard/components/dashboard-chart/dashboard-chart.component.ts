import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    viewChild,
} from '@angular/core';
import {
    ArcElement,
    BarController,
    BarElement,
    CategoryScale,
    Chart,
    ChartConfiguration,
    DoughnutController,
    LinearScale,
    LineController,
    LineElement,
    PointElement,
    Tooltip,
} from 'chart.js';

import { DashboardChartSeries, DashboardChartType } from '../../models/dashboard-chart.model';

Chart.register(
    BarController,
    BarElement,
    LineController,
    LineElement,
    PointElement,
    DoughnutController,
    ArcElement,
    CategoryScale,
    LinearScale,
    Tooltip
);

@Component({
    selector: 'app-dashboard-chart',
    template: `<canvas
        #canvas
        role="img"
        [attr.aria-label]="ariaLabel()"
    ></canvas>`,
    styles: `
        :host {
            display: block;
            position: relative;
            height: 220px;
        }
    `,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardChartComponent {
    readonly type = input.required<DashboardChartType>();
    readonly labels = input.required<string[]>();
    readonly series = input.required<DashboardChartSeries[]>();
    readonly ariaLabel = input('');

    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
    private chart?: Chart<'bar' | 'line' | 'doughnut'>;

    constructor() {
        effect(() => {
            const config = toConfig(this.type(), this.labels(), this.series(), (token) => this.resolve(token));
            this.chart?.destroy();
            this.chart = new Chart(this.canvas().nativeElement, config);
        });
        inject(DestroyRef).onDestroy(() => this.chart?.destroy());
    }

    private resolve(token: string): string {
        return getComputedStyle(this.host.nativeElement).getPropertyValue(token).trim();
    }
}

function toConfig(
    type: DashboardChartType,
    labels: string[],
    series: DashboardChartSeries[],
    color: (token: string) => string
): ChartConfiguration<'bar' | 'line' | 'doughnut'> {
    const base = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false as const,
        interaction: { mode: 'index' as const, intersect: false },
        plugins: { legend: { display: false } },
    };
    if (type === 'donut') {
        return {
            type: 'doughnut',
            data: {
                labels: series.map((s) => s.label),
                datasets: [
                    {
                        data: series.map((s) => s.values.reduce((sum, value) => sum + value, 0)),
                        backgroundColor: series.map((s) => color(s.color)),
                        borderWidth: 0,
                    },
                ],
            },
            options: { ...base, cutout: '70%' },
        };
    }
    const stacked = type === 'columns';
    const ticks = { color: color('--color-text-secondary') };
    return {
        type: stacked ? 'bar' : 'line',
        data: {
            labels,
            datasets: series.map((s) => ({
                label: s.label,
                data: s.values,
                backgroundColor: color(s.color),
                borderColor: color(s.color),
                pointRadius: 0,
                tension: 0.3,
            })),
        },
        options: {
            ...base,
            scales: {
                x: { stacked, ticks, grid: { display: false } },
                y: {
                    stacked,
                    beginAtZero: true,
                    ticks: { ...ticks, precision: 0 },
                    grid: { color: color('--color-divider') },
                },
            },
        },
    };
}

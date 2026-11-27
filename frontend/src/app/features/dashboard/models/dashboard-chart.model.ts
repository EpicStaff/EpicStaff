export type DashboardChartType = 'columns' | 'lines' | 'donut';

export interface DashboardChartSeries {
    label: string;
    color: string;
    values: number[];
}

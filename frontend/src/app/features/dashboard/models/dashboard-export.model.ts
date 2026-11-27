import { Signal } from '@angular/core';
import { CsvCell } from '@shared/utils';

export interface DashboardCsvSection {
    title: string;
    header: string[];
    rows: CsvCell[][];
}

export interface DashboardExportSource {
    name: string;
    sections: Signal<DashboardCsvSection[]>;
}

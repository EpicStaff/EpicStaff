import { computed, DestroyRef, Injectable, signal } from '@angular/core';
import { downloadCsv } from '@shared/utils';

import { DashboardExportSource } from '../models/dashboard-export.model';
import { toIsoDate } from '../utils/dashboard-range.util';

@Injectable()
export class DashboardExportService {
    private readonly source = signal<DashboardExportSource | null>(null);

    readonly canExport = computed(() => (this.source()?.sections().length ?? 0) > 0);

    register(source: DashboardExportSource, destroyRef: DestroyRef): void {
        this.source.set(source);
        destroyRef.onDestroy(() => this.source.set(null));
    }

    export(): void {
        const source = this.source();
        if (!source) return;
        const rows = source
            .sections()
            .flatMap((section, index) => [...(index ? [[]] : []), [section.title], section.header, ...section.rows]);
        downloadCsv(rows, `dashboard-${source.name}-${toIsoDate(new Date())}.csv`);
    }
}

import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
    selector: 'app-first-report-state',
    templateUrl: './first-report-state.component.html',
    styleUrls: ['./first-report-state.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FirstReportStateComponent {}

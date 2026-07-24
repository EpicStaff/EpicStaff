import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
    selector: 'app-api-keys-tab',
    templateUrl: './api-keys-tab.component.html',
    styleUrls: ['./api-keys-tab.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApiKeysTabComponent {}

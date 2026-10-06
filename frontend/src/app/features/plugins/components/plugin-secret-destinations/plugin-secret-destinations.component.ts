import { Component, computed, input } from '@angular/core';

import { PluginSecretDestination } from '../../models/plugin.model';
import { describeSecretDestination } from '../../utils/plugin-display.util';

/** Under a secret slot's input: every endpoint its value is sent to, with custom hosts called out. */
@Component({
    selector: 'app-plugin-secret-destinations',
    templateUrl: './plugin-secret-destinations.component.html',
    styleUrls: ['./plugin-secret-destinations.component.scss'],
})
export class PluginSecretDestinationsComponent {
    readonly destinations = input.required<readonly PluginSecretDestination[]>();

    protected readonly lines = computed(() => this.destinations().map(describeSecretDestination));
}

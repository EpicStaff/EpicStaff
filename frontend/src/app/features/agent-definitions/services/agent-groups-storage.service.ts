import { inject, Injectable } from '@angular/core';
import { BaseLabelsStore } from '@shared/services';

import { AgentGroupsApiService } from './agent-groups-api.service';

/**
 * Groups of agents and shared surfaces. All state lives in BaseLabelsStore; this subclass only wires
 * the `agent-labels/` API. Groups are flat: always create them with a null parent.
 */
@Injectable({ providedIn: 'root' })
export class AgentGroupsStorageService extends BaseLabelsStore {
    protected readonly api = inject(AgentGroupsApiService);
}

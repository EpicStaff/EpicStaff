import { inject, Injectable } from '@angular/core';
import {
    CreateGeminiRealtimeConfigRequest,
    GeminiRealtimeConfig,
    UpdateGeminiRealtimeConfigRequest,
} from '@shared/models';
import { GeminiRealtimeConfigService } from '@shared/services';

import { BaseRealtimeConfigStorageService } from './base-realtime-config-storage.service';

@Injectable({ providedIn: 'root' })
export class GeminiRealtimeConfigStorageService extends BaseRealtimeConfigStorageService<
    GeminiRealtimeConfig,
    CreateGeminiRealtimeConfigRequest,
    UpdateGeminiRealtimeConfigRequest
> {
    protected override readonly api = inject(GeminiRealtimeConfigService);
}

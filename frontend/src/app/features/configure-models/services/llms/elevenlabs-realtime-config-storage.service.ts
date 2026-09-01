import { inject, Injectable } from '@angular/core';

import {
    CreateElevenLabsRealtimeConfigRequest,
    ElevenLabsRealtimeConfig,
    UpdateElevenLabsRealtimeConfigRequest,
} from '../../../../shared/models/realtime-voice/elevenlabs-realtime-config.model';
import { ElevenLabsRealtimeConfigService } from '../../../../shared/services/realtime-llms/elevenlabs-realtime-config.service';
import { BaseRealtimeConfigStorageService } from './base-realtime-config-storage.service';

@Injectable({ providedIn: 'root' })
export class ElevenLabsRealtimeConfigStorageService extends BaseRealtimeConfigStorageService<
    ElevenLabsRealtimeConfig,
    CreateElevenLabsRealtimeConfigRequest,
    UpdateElevenLabsRealtimeConfigRequest
> {
    protected override readonly api = inject(ElevenLabsRealtimeConfigService);
}

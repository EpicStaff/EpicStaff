import { inject, Injectable } from '@angular/core';

import {
    CreateOpenAIRealtimeConfigRequest,
    OpenAIRealtimeConfig,
    UpdateOpenAIRealtimeConfigRequest,
} from '../../../../shared/models/realtime-voice/openai-realtime-config.model';
import { OpenAIRealtimeConfigService } from '../../../../shared/services/realtime-llms/openai-realtime-config.service';
import { BaseRealtimeConfigStorageService } from './base-realtime-config-storage.service';

@Injectable({ providedIn: 'root' })
export class OpenAIRealtimeConfigStorageService extends BaseRealtimeConfigStorageService<
    OpenAIRealtimeConfig,
    CreateOpenAIRealtimeConfigRequest,
    UpdateOpenAIRealtimeConfigRequest
> {
    protected override readonly api = inject(OpenAIRealtimeConfigService);
}

import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { EditorInfo } from '../../../../../../../features/flows/services/graph-collaboration.ws.service';
import { ProfileService } from '../../../../../../../services/auth/profile.service';
import { GraphPresenceAvatarComponent } from './graph-presence-avatar.component';

@Component({
    selector: 'app-graph-presence-indicators',
    imports: [MatTooltipModule, GraphPresenceAvatarComponent],
    templateUrl: './graph-presence-indicators.component.html',
    styleUrl: './graph-presence-indicators.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphPresenceIndicatorsComponent {
    private readonly profileService = inject(ProfileService);

    readonly editors = input<EditorInfo[]>([]);

    private readonly filtered = computed(() => {
        const currentId = this.profileService.currentUserSignal()?.id;
        return this.editors().filter((e) => e.user_id !== currentId);
    });

    protected readonly visibleEditors = computed(() => this.filtered().slice(0, 3));
    protected readonly hiddenCount = computed(() => Math.max(0, this.filtered().length - 3));
    protected readonly hiddenTooltip = computed(() =>
        this.filtered()
            .slice(3)
            .map((e) => e.display_name ?? `User ${e.user_id}`)
            .join('\n')
    );

    protected getTooltip(editor: EditorInfo): string {
        return editor.display_name ?? `User ${editor.user_id}`;
    }
}

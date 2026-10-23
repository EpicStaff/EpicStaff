import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { EditorInfo } from '../../../../../../../features/flows/services/graph-collaboration.ws.service';
import { ProfileService } from '../../../../../../../services/auth/profile.service';
import { ConfigService } from '../../../../../../../services/config';

const AVATAR_COLORS = ['#4A90D9', '#7B68EE', '#E05C5C', '#4ECDC4', '#45B7D1', '#96CEB4', '#D4A843', '#C47ED4'];

@Component({
    selector: 'app-graph-presence-indicators',
    imports: [MatTooltipModule],
    templateUrl: './graph-presence-indicators.component.html',
    styleUrl: './graph-presence-indicators.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphPresenceIndicatorsComponent {
    private readonly profileService = inject(ProfileService);
    private readonly configService = inject(ConfigService);

    private get mediaBase(): string {
        return this.configService.apiUrl.replace(/\/api\/$/, '');
    }

    readonly editors = input<EditorInfo[]>([]);

    // Avatar links are signed and expire; a URL that failed once shows initials instead of a broken image.
    private readonly failedAvatarUrls = signal<ReadonlySet<string>>(new Set());

    private readonly filtered = computed(() => {
        const currentId = this.profileService.currentUserSignal()?.id;
        return this.editors().filter((e) => e.user_id !== currentId);
    });

    protected readonly visibleEditors = computed(() =>
        this.filtered()
            .slice(0, 3)
            .map((e) => ({ ...e, resolvedAvatarUrl: this.displayableAvatarUrl(e.avatar_url) }))
    );
    protected readonly hiddenCount = computed(() => Math.max(0, this.filtered().length - 3));
    protected readonly hiddenTooltip = computed(() =>
        this.filtered()
            .slice(3)
            .map((e) => e.display_name ?? `User ${e.user_id}`)
            .join('\n')
    );

    protected getColor(userId: number): string {
        return AVATAR_COLORS[userId % AVATAR_COLORS.length];
    }

    protected getInitials(editor: EditorInfo): string {
        if (!editor.display_name) return `U${editor.user_id}`;
        const words = editor.display_name.trim().split(/\s+/);
        return words.length >= 2 ? (words[0][0] + words[1][0]).toUpperCase() : words[0][0].toUpperCase();
    }

    protected getTooltip(editor: EditorInfo): string {
        return editor.display_name ?? `User ${editor.user_id}`;
    }

    protected onAvatarError(url: string): void {
        this.failedAvatarUrls.update((failed) => new Set(failed).add(url));
    }

    protected resolveAvatarUrl(url: string | null | undefined): string | null {
        if (!url) return null;
        if (url.startsWith('http')) return url;
        return `${this.mediaBase}${url}`;
    }

    private displayableAvatarUrl(url: string | null | undefined): string | null {
        const resolved = this.resolveAvatarUrl(url);
        return resolved && !this.failedAvatarUrls().has(resolved) ? resolved : null;
    }
}

import { Component, computed, input } from '@angular/core';
import { injectAvatarObjectUrl } from '@shared/services';

import { EditorInfo } from '../../../../../../../features/flows/services/graph-collaboration.ws.service';

const AVATAR_COLORS = ['#4A90D9', '#7B68EE', '#E05C5C', '#4ECDC4', '#45B7D1', '#96CEB4', '#D4A843', '#C47ED4'];

/** One co-editor's avatar: the image once it has loaded, the initials on a per-user colour until then or without one. */
@Component({
    selector: 'app-graph-presence-avatar',
    templateUrl: './graph-presence-avatar.component.html',
    styleUrl: './graph-presence-avatar.component.scss',
    host: {
        '[style.background-color]': 'backgroundColor()',
    },
})
export class GraphPresenceAvatarComponent {
    readonly editor = input.required<EditorInfo>();

    protected readonly imageSrc = injectAvatarObjectUrl(computed(() => this.editor().avatar_url ?? null));
    protected readonly initials = computed(() => {
        const editor = this.editor();
        const name = editor.display_name?.trim();
        if (!name) return `U${editor.user_id}`;
        const words = name.split(/\s+/);
        return words.length >= 2 ? (words[0][0] + words[1][0]).toUpperCase() : words[0][0].toUpperCase();
    });
    protected readonly backgroundColor = computed(() =>
        this.imageSrc() ? 'transparent' : AVATAR_COLORS[this.editor().user_id % AVATAR_COLORS.length]
    );
}

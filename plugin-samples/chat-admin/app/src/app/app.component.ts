import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { ChatStore } from './chat/chat-store.service';
import { PluginBridgeService } from './core/plugin-bridge.service';

type Section = 'chat' | 'conversations' | 'about';

/** The app shell: its own header and tabs inside EpicStaff's content area, and the routed page. */
@Component({
    selector: 'app-root',
    imports: [RouterLink, RouterOutlet],
    templateUrl: './app.component.html',
    styleUrl: './app.component.css',
})
export class AppComponent {
    private readonly router = inject(Router);
    private readonly bridgeService = inject(PluginBridgeService);
    private readonly chatStore = inject(ChatStore);

    private readonly url = toSignal(
        this.router.events.pipe(
            filter((event): event is NavigationEnd => event instanceof NavigationEnd),
            map((event) => event.urlAfterRedirects)
        ),
        { initialValue: this.router.url }
    );
    protected readonly section = computed<Section>(() => {
        const first = this.url()
            .split(/[/?#]/)
            .find((segment) => segment !== '');
        return first === 'conversations' || first === 'about' ? first : 'chat';
    });
    protected readonly pluginName = computed(() => this.bridgeService.context()?.plugin.name || 'Chat Admin');
    protected readonly mocked = this.bridgeService.mocked;
    protected readonly connectionError = this.bridgeService.connectionError;
    /** The Chat tab returns to the open conversation rather than starting a new one. */
    protected readonly chatLink = computed(() =>
        this.chatStore.isEmpty() && !this.chatStore.saved() ? ['/chat'] : ['/chat', this.chatStore.conversationId()]
    );
}

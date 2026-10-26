import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, ElementRef, inject, OnInit, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { ButtonComponent, SpinnerComponent } from '@shared/components';

import { PluginIconComponent } from '../../components/plugin-icon/plugin-icon.component';
import { PLUGIN_LOGIN_CONTINUE_PARAMETER } from '../../constants/plugin-login-protocol.constants';
import { PluginOrganizationRef } from '../../models/plugin-admin.model';
import { PluginLoginOrganizations } from '../../models/plugin-login.model';
import { PluginLoginApiService } from '../../services/plugin-login-api.service';
import { PluginLoginNavigationService } from '../../services/plugin-login-navigation.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import {
    continueWithOrganization,
    parsePluginLoginContinue,
    PluginLoginContinue,
} from '../../utils/plugin-login-continue.util';

type LoginPlugin = PluginLoginOrganizations['plugin'];

interface ChoiceView {
    kind: 'choice';
    plugin: LoginPlugin;
    organizations: PluginOrganizationRef[];
}

interface MessageView {
    kind: 'message';
    plugin: LoginPlugin | null;
    title: string;
    text: string;
    canRetry: boolean;
}

type ChooserView = { kind: 'loading' } | ChoiceView | MessageView;

const LOAD_FAILED_FALLBACK = 'Check your connection and try again.';

/**
 * `/plugin-choose-org?continue=…`: where EpicStaff's authorize endpoint sends a signed-in person who may open the
 * plugin in more than one of their organizations. Picking one continues the sign-in with that `org`. Works top-level
 * and inside the plugin's frame. `continue` is followed only when it is EpicStaff's authorize request.
 */
@Component({
    selector: 'app-plugin-org-chooser-page',
    imports: [ButtonComponent, PluginIconComponent, SpinnerComponent],
    templateUrl: './plugin-org-chooser-page.component.html',
    styleUrl: './plugin-org-chooser-page.component.scss',
})
export class PluginOrgChooserPageComponent implements OnInit {
    private readonly choiceTitle = viewChild<ElementRef<HTMLElement>>('choiceTitle');

    protected readonly view = signal<ChooserView>({ kind: 'loading' });
    protected readonly isLoading = computed(() => this.view().kind === 'loading');
    protected readonly choice = computed(() => {
        const view = this.view();
        return view.kind === 'choice' ? view : null;
    });
    protected readonly message = computed(() => {
        const view = this.view();
        return view.kind === 'message' ? view : null;
    });

    /** When the choices appear, the focus goes to their heading, so a screen reader starts there. */
    private readonly focusChoices = effect(() => this.choiceTitle()?.nativeElement.focus());

    private readonly route = inject(ActivatedRoute);
    private readonly router = inject(Router);
    private readonly destroyRef = inject(DestroyRef);
    private readonly loginApi = inject(PluginLoginApiService);
    private readonly navigation = inject(PluginLoginNavigationService);
    private target: PluginLoginContinue | null = null;

    ngOnInit(): void {
        this.target = parsePluginLoginContinue(this.route.snapshot.queryParamMap.get(PLUGIN_LOGIN_CONTINUE_PARAMETER));
        if (this.target === null) {
            void this.router.navigateByUrl('/', { replaceUrl: true });
            return;
        }
        this.load();
    }

    protected load(): void {
        const target = this.target;
        if (target === null) return;
        this.view.set({ kind: 'loading' });
        this.loginApi
            .loginOrganizations(target.plugin)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => this.view.set(this.viewFor(response)),
                error: (error: unknown) => this.view.set(this.viewForError(error)),
            });
    }

    protected choose(organization: PluginOrganizationRef): void {
        if (this.target !== null) this.navigation.continueTo(continueWithOrganization(this.target, organization.id));
    }

    private viewFor(response: PluginLoginOrganizations): ChooserView {
        if (response.organizations.length > 0) {
            return { kind: 'choice', plugin: response.plugin, organizations: response.organizations };
        }
        return {
            kind: 'message',
            plugin: response.plugin,
            title: `You can't open ${response.plugin.name} in any of your organizations`,
            text: 'Ask an administrator of your organization to give you access.',
            canRetry: false,
        };
    }

    private viewForError(error: unknown): MessageView {
        if (error instanceof HttpErrorResponse && error.status === HttpStatusCode.NotFound) {
            return {
                kind: 'message',
                plugin: null,
                title: 'This plugin is not available',
                text: 'It may have been removed or stopped.',
                canRetry: false,
            };
        }
        return {
            kind: 'message',
            plugin: null,
            title: "Couldn't load your organizations",
            text: toPluginErrorView(error, LOAD_FAILED_FALLBACK).message,
            canRetry: true,
        };
    }
}

import { Component, forwardRef, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../../../../services/auth/auth.service';
import { LoginPageComponent } from '../../../auth/components/login-page/login-page.component';
import { POST_LOGIN_STEP, PostLoginStep } from '../../../auth/components/login-page/post-login-step';
import { PLUGIN_LOGIN_CONTINUE_PARAMETER } from '../../constants/plugin-login-protocol.constants';
import { PluginLoginAutoContinueService } from '../../services/plugin-login-auto-continue.service';
import { PluginLoginNavigationService } from '../../services/plugin-login-navigation.service';
import { parsePluginLoginContinue, PluginLoginContinue } from '../../utils/plugin-login-continue.util';

/**
 * `/plugin-login?continue=…`: where EpicStaff's authorize endpoint sends a person who is not signed in while a plugin
 * page signs them in. It often renders inside the plugin's frame. A person already signed in continues at once, once
 * per sign-in (if the same sign-in comes back, the form is shown instead of going round again); anyone else gets
 * EpicStaff's own login form, and continues after it. `continue` is followed only when it is EpicStaff's authorize
 * request; anything else goes to EpicStaff's start page.
 */
@Component({
    selector: 'app-plugin-login-continue-page',
    imports: [LoginPageComponent],
    template: `
        @if (showLoginForm()) {
            <app-login-page />
        }
    `,
    providers: [{ provide: POST_LOGIN_STEP, useExisting: forwardRef(() => PluginLoginContinuePageComponent) }],
})
export class PluginLoginContinuePageComponent implements OnInit, PostLoginStep {
    protected readonly showLoginForm = signal(false);

    private readonly route = inject(ActivatedRoute);
    private readonly router = inject(Router);
    private readonly authService = inject(AuthService);
    private readonly navigation = inject(PluginLoginNavigationService);
    private readonly autoContinue = inject(PluginLoginAutoContinueService);
    private target: PluginLoginContinue | null = null;

    ngOnInit(): void {
        this.target = parsePluginLoginContinue(this.route.snapshot.queryParamMap.get(PLUGIN_LOGIN_CONTINUE_PARAMETER));
        if (this.target === null) {
            void this.router.navigateByUrl('/', { replaceUrl: true });
            return;
        }
        // The app restored the session before routing; signed in means the sign-in can go on at once.
        if (this.authService.isAuthenticated() && this.autoContinue.claim(this.target.state)) {
            this.navigation.continueTo(this.target.path);
            return;
        }
        this.showLoginForm.set(true);
    }

    continueAfterLogin(): void {
        if (this.target !== null) this.navigation.continueTo(this.target.path);
    }
}

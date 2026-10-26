import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { of } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';
import { LoginPageComponent } from '../../../auth/components/login-page/login-page.component';
import { PluginLoginAutoContinueService } from '../../services/plugin-login-auto-continue.service';
import { PluginLoginNavigationService } from '../../services/plugin-login-navigation.service';
import { PluginLoginContinuePageComponent } from './plugin-login-continue-page.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const CONTINUE = `/api/auth/plugin-authorize/?plugin=weather&state=${'S'.repeat(43)}&code_challenge=${'C'.repeat(
    43
)}&code_challenge_method=S256`;

describe('PluginLoginContinuePageComponent', () => {
    const navigation = { continueTo: vi.fn() };
    const autoContinue = { claim: vi.fn(() => true) };
    const router = { navigate: vi.fn(), navigateByUrl: vi.fn() };
    const login = vi.fn(() => of(true));
    let authenticated: boolean;

    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        authenticated = false;
    });

    function render(continueParameter: string | null): ComponentFixture<PluginLoginContinuePageComponent> {
        TestBed.configureTestingModule({
            imports: [PluginLoginContinuePageComponent],
            providers: [
                { provide: PluginLoginNavigationService, useValue: navigation },
                { provide: PluginLoginAutoContinueService, useValue: autoContinue },
                { provide: Router, useValue: router },
                {
                    provide: ActivatedRoute,
                    useValue: {
                        snapshot: {
                            queryParamMap: convertToParamMap(
                                continueParameter === null ? {} : { continue: continueParameter }
                            ),
                        },
                    },
                },
                {
                    provide: AuthService,
                    useValue: {
                        isAuthenticated: () => authenticated,
                        getStatus: () => of({ needs_setup: false }),
                        login,
                    },
                },
                { provide: ToastService, useValue: { info: vi.fn() } },
            ],
        });
        const fixture = TestBed.createComponent(PluginLoginContinuePageComponent);
        fixture.detectChanges();
        return fixture;
    }

    function loginForm(fixture: ComponentFixture<PluginLoginContinuePageComponent>): Element | null {
        return (fixture.nativeElement as HTMLElement).querySelector('app-login-page');
    }

    it('continues at once when the session is already restored, without showing the form', () => {
        authenticated = true;

        const fixture = render(CONTINUE);

        expect(navigation.continueTo).toHaveBeenCalledExactlyOnceWith(CONTINUE);
        expect(autoContinue.claim).toHaveBeenCalledExactlyOnceWith('S'.repeat(43));
        expect(loginForm(fixture)).toBeNull();
    });

    it('shows the login form instead of continuing the same sign-in a second time', () => {
        authenticated = true;
        autoContinue.claim.mockReturnValueOnce(false);

        const fixture = render(CONTINUE);

        expect(navigation.continueTo).not.toHaveBeenCalled();
        expect(loginForm(fixture)).not.toBeNull();
    });

    it('shows EpicStaff’s login form, and continues with replace after a successful login', () => {
        const fixture = render(CONTINUE);
        expect(loginForm(fixture)).not.toBeNull();
        expect(navigation.continueTo).not.toHaveBeenCalled();
        const page = fixture.nativeElement as HTMLElement;
        expect(page.querySelector('.forgot-label')).toBeNull();
        expect(page.querySelector('.prompt')).toBeNull();

        const loginPage = fixture.debugElement.query(By.directive(LoginPageComponent))
            .componentInstance as LoginPageComponent;
        loginPage.form.setValue({ email: 'ada@acme.test', password: 'password-123', rememberMe: false });
        loginPage.onSubmit();

        expect(login).toHaveBeenCalledWith('ada@acme.test', 'password-123', false);
        expect(navigation.continueTo).toHaveBeenCalledExactlyOnceWith(CONTINUE);
        expect(router.navigateByUrl).not.toHaveBeenCalled();
    });

    it.each([
        ['missing', null],
        ['another origin', `https://evil.example${CONTINUE}`],
        ['protocol-relative', `//evil.example${CONTINUE}`],
        ['with prompt', `${CONTINUE}&prompt=none`],
        ['another path', '/api/auth/logout/?plugin=weather'],
    ])('goes to EpicStaff’s start page in-app for a %s continue, never to it', (_name, value) => {
        authenticated = true;

        const fixture = render(value);

        expect(router.navigateByUrl).toHaveBeenCalledExactlyOnceWith('/', { replaceUrl: true });
        expect(navigation.continueTo).not.toHaveBeenCalled();
        expect(loginForm(fixture)).toBeNull();
    });
});

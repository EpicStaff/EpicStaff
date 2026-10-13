import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { CHAT_BINDING_DEFAULTS, ChatBinding, ChatMyAliasResult } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';
import { MY_DESK_ALIAS_TITLE_ID, MyDeskAliasDialogComponent } from './my-desk-alias-dialog.component';

const binding: ChatBinding = {
    ...CHAT_BINDING_DEFAULTS,
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Sales',
    bot_display_name: 'Ava',
    operator_display_name: 'Support',
    public_key: 'pk',
    is_active: true,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
};

// The dialog's buttons collapse their labels on overflow, which jsdom cannot measure.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const refusal = (status: number, error: unknown): Observable<never> =>
    throwError(() => new HttpErrorResponse({ status, error }));

describe('MyDeskAliasDialogComponent', () => {
    let fixture: ComponentFixture<MyDeskAliasDialogComponent>;
    const chatApi = { setMyAlias: vi.fn() };
    const dialogRef = { close: vi.fn() };

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const field = (): HTMLInputElement => host().querySelector('input')!;
    const error = (): HTMLElement | null => host().querySelector('.alias-dialog__error');
    const button = (label: string): HTMLButtonElement =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('button')).find(
            (candidate) => candidate.textContent?.trim() === label
        )!;

    /** Opens the dialog for the desk, with the user going by `alias` there now. */
    function open(alias: string | null = null): void {
        if (alias) {
            TestBed.inject(ChatMyAliasesStorageService).remember({ binding_id: 'b-1', alias, visible_name: alias });
        }
        fixture = TestBed.createComponent(MyDeskAliasDialogComponent);
        fixture.detectChanges();
    }

    function type(value: string): void {
        field().value = value;
        field().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function save(): void {
        button('Save').click();
        fixture.detectChanges();
    }

    const result = (alias: string | null): ChatMyAliasResult => ({
        binding_id: 'b-1',
        alias,
        visible_name: alias ?? 'Support',
    });

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        TestBed.configureTestingModule({
            imports: [MyDeskAliasDialogComponent],
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: DialogRef, useValue: dialogRef },
                { provide: DIALOG_DATA, useValue: { binding } },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    describe('form', () => {
        it('is titled for screen readers, and labels, describes and prefills its one field', async () => {
            open('Mike');
            await fixture.whenStable();
            const title = host().querySelector('h2')!;
            expect(title.id).toBe(MY_DESK_ALIAS_TITLE_ID);
            expect(title.textContent?.trim()).toBe('My name on this desk');

            const input = field();
            expect(input.value).toBe('Mike');
            expect(host().querySelector(`label[for="${input.id}"]`)?.textContent?.trim()).toBe('Name visitors see');
            expect(input.placeholder).toBe('Support');
            // The dialog opens with the focus on it (the CDK focus trap honours cdkFocusInitial).
            expect(input.hasAttribute('cdkFocusInitial')).toBe(true);
            const hint = document.getElementById(input.getAttribute('aria-describedby')!);
            expect(hint?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
                'Visitors on “Sales” see this name on your replies. Leave blank to use “Support”.'
            );
            expect(input.getAttribute('aria-invalid')).toBe('false');
        });

        it('starts empty when the user goes by the desk name', () => {
            open();
            expect(field().value).toBe('');
        });
    });

    describe('saving', () => {
        it('saves the trimmed name in composed form, stores the answer and closes with it', () => {
            open();
            chatApi.setMyAlias.mockReturnValueOnce(of(result('José')));
            // A decomposed accent (e + U+0301) is sent composed, as the service stores it.
            type(`  Jose${String.fromCodePoint(0x301)} `);
            save();

            expect(chatApi.setMyAlias).toHaveBeenCalledWith('b-1', 'José');
            expect(TestBed.inject(ChatMyAliasesStorageService).aliasFor('b-1')).toBe('José');
            expect(dialogRef.close).toHaveBeenCalledWith(result('José'));
        });

        it("strips what the server strips (its whitespace, not JavaScript's) before checking and sending", () => {
            open();
            chatApi.setMyAlias.mockReturnValueOnce(of(result('Mike')));
            // Information separators and NEL are whitespace to the server's strip(), not to trim().
            type(`${String.fromCodePoint(0x1f, 0x85)} Mike${String.fromCodePoint(0x3000, 0x1c)}`);
            save();
            expect(error()).toBeNull();
            expect(chatApi.setMyAlias).toHaveBeenCalledWith('b-1', 'Mike');
        });

        it('keeps a byte order mark the server would not strip, and refuses it as it does', () => {
            open();
            type(`${String.fromCodePoint(0xfeff)}Mike`);
            save();
            expect(error()?.textContent?.trim()).toBe(
                'Remove the invisible or control character U+FEFF: visitors would not see it.'
            );
            expect(chatApi.setMyAlias).not.toHaveBeenCalled();
        });

        it('clears the name when the field is left blank', () => {
            open('Mike');
            chatApi.setMyAlias.mockReturnValueOnce(of(result(null)));
            type('   ');
            save();

            expect(chatApi.setMyAlias).toHaveBeenCalledWith('b-1', null);
            expect(TestBed.inject(ChatMyAliasesStorageService).aliasFor('b-1')).toBeNull();
            expect(dialogRef.close).toHaveBeenCalledWith(result(null));
        });

        it('closes without a request when the name did not change', () => {
            open('Mike');
            type(' Mike ');
            save();
            expect(chatApi.setMyAlias).not.toHaveBeenCalled();
            expect(dialogRef.close).toHaveBeenCalledWith();
        });

        it('saves on Enter too, sends one request while saving, and says it is saving', () => {
            open();
            chatApi.setMyAlias.mockReturnValueOnce(new Subject<ChatMyAliasResult>());
            type('Mike');
            // Enter in the field submits the form.
            host().querySelector('form')!.dispatchEvent(new Event('submit'));
            fixture.detectChanges();
            expect(button('Saving...')).toBeDefined();
            button('Saving...').click();
            host().querySelector('form')!.dispatchEvent(new Event('submit'));
            expect(chatApi.setMyAlias).toHaveBeenCalledTimes(1);
        });

        it('closes without a result on Cancel and on the close button', () => {
            open();
            button('Cancel').click();
            (host().querySelector('[aria-label="Close dialog"]') as HTMLButtonElement).click();
            expect(dialogRef.close).toHaveBeenCalledTimes(2);
            expect(dialogRef.close.mock.calls.every((call) => call.length === 0)).toBe(true);
        });
    });

    describe('checks before sending', () => {
        function refused(value: string): string | null {
            type(value);
            save();
            return error()?.textContent?.trim() ?? null;
        }

        /** A refusal naming the character, as the check words it. */
        const invisible = (codePoint: string): string =>
            `Remove the invisible or control character U+${codePoint}: visitors would not see it.`;
        const around = (codePoint: number): string => `Mi${String.fromCodePoint(codePoint)}ke`;

        beforeEach(() => open());

        it('refuses more than 64 characters, counting characters rather than UTF-16 units', () => {
            expect(refused('a'.repeat(65))).toBe('Use at most 64 characters.');
            // 64 emoji are 128 UTF-16 units but 64 characters.
            const emoji = String.fromCodePoint(0x1f600).repeat(64);
            chatApi.setMyAlias.mockReturnValueOnce(of(result(emoji)));
            expect(refused(emoji)).toBeNull();
            expect(chatApi.setMyAlias).toHaveBeenCalledTimes(1);
        });

        it('refuses control, format and direction-changing characters, naming the one found', () => {
            expect(refused(around(0x202e))).toBe(invisible('202E'));
            expect(refused(around(0x0007))).toBe(invisible('0007'));
            expect(refused(around(0x200b))).toBe(invisible('200B'));
            expect(refused(around(0x2028))).toBe(invisible('2028'));
            expect(chatApi.setMyAlias).not.toHaveBeenCalled();
        });

        it('refuses the fillers that render as nothing although their kind is allowed', () => {
            const fillers: [number, string][] = [
                [0x034f, '034F'],
                [0x115f, '115F'],
                [0x17b4, '17B4'],
                [0x180b, '180B'],
                [0x2800, '2800'],
                [0x3164, '3164'],
                [0xffa0, 'FFA0'],
                [0xfe00, 'FE00'],
                [0xfe0d, 'FE0D'],
                [0x1bca0, '1BCA0'],
                [0x1d173, '1D173'],
                [0xe0041, 'E0041'],
            ];
            for (const [codePoint, name] of fillers) expect(refused(around(codePoint))).toBe(invisible(name));
            expect(chatApi.setMyAlias).not.toHaveBeenCalled();
        });

        it('keeps the zero width joiner and variation selectors 15 and 16 that emoji need', () => {
            // A technologist (joiner), a red heart in emoji style (selector 16), a rainbow flag (both).
            const emoji = String.fromCodePoint(
                0x1f469,
                0x200d,
                0x1f4bb,
                0x20,
                0x2764,
                0xfe0f,
                0x20,
                0x1f3f3,
                0xfe0f,
                0x200d,
                0x1f308,
                0x20,
                0x2764,
                0xfe0e
            );
            chatApi.setMyAlias.mockReturnValueOnce(of(result(`Dev ${emoji}`)));
            expect(refused(`Dev ${emoji}`)).toBeNull();
            expect(chatApi.setMyAlias).toHaveBeenCalledWith('b-1', `Dev ${emoji}`);
        });

        it("refuses the desk's bot name, whatever its case or the joiners added to it", () => {
            expect(refused(' ava ')).toBe("That's the bot's name on this desk");
            expect(refused(`Ava${String.fromCodePoint(0x200d)}`)).toBe("That's the bot's name on this desk");
            expect(refused(`A${String.fromCodePoint(0xfe0f)}VA`)).toBe("That's the bot's name on this desk");
            expect(chatApi.setMyAlias).not.toHaveBeenCalled();
        });

        it('speaks up only after leaving the field or trying to save, then as the user types', () => {
            type('a'.repeat(65));
            expect(error()).toBeNull();

            field().dispatchEvent(new Event('blur'));
            fixture.detectChanges();
            expect(error()?.textContent?.trim()).toBe('Use at most 64 characters.');
            expect(error()?.getAttribute('role')).toBe('alert');
            expect(field().getAttribute('aria-invalid')).toBe('true');
            expect(field().getAttribute('aria-describedby')?.split(' ')).toContain(error()!.id);

            type('Mike');
            expect(error()).toBeNull();
            expect(field().getAttribute('aria-invalid')).toBe('false');
        });
    });

    describe('the bot name check on a desk whose bot is "Straße"', () => {
        beforeEach(() => {
            TestBed.overrideProvider(DIALOG_DATA, {
                useValue: { binding: { ...binding, bot_display_name: `Stra${String.fromCodePoint(0xdf)}e` } },
            });
            open();
        });

        it('reads "STRASSE" and "strasse" as the bot\'s name, as full case folding does', () => {
            for (const name of ['STRASSE', 'strasse', `STRA${String.fromCodePoint(0x1e9e)}E`]) {
                type(name);
                save();
                expect(error()?.textContent?.trim()).toBe("That's the bot's name on this desk");
            }
            expect(chatApi.setMyAlias).not.toHaveBeenCalled();
        });
    });

    describe("the server's refusals, said under the field", () => {
        beforeEach(() => open());

        function refusedWith(answer: Observable<never>): string | null {
            chatApi.setMyAlias.mockReturnValueOnce(answer);
            type('Mike');
            save();
            return error()?.textContent?.trim() ?? null;
        }

        it('says another operator on the desk uses the name, keeps the dialog open and the focus on the field', () => {
            expect(refusedWith(refusal(409, { code: 'alias_taken', message: 'taken' }))).toBe(
                'Another operator on this desk already uses this name'
            );
            expect(dialogRef.close).not.toHaveBeenCalled();
            expect(document.activeElement).toBe(field());
            expect(button('Save').closest('app-button')).not.toBeNull();

            // Gone with the next edit.
            type('Mikey');
            expect(error()).toBeNull();
        });

        it("says when the name is the desk's bot name", () => {
            expect(refusedWith(refusal(409, { code: 'alias_reserved', message: 'reserved' }))).toBe(
                "That's the bot's name on this desk"
            );
        });

        it('says what a validation error refused, else the message of any other failure', () => {
            expect(
                refusedWith(
                    refusal(400, {
                        code: 'validation_error',
                        message: 'Validation failed',
                        errors: [{ message: 'Value error, Must be plain text: U+2800 is not allowed.', key: 'alias' }],
                    })
                )
            ).toBe('Must be plain text: U+2800 is not allowed.');

            expect(refusedWith(refusal(404, { code: 'not_found', message: 'This desk no longer exists.' }))).toBe(
                'This desk no longer exists.'
            );
        });
    });
});

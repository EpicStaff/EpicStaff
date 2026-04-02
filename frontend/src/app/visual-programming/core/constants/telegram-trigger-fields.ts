import {
    TelegramFieldParent,
    TelegramTriggerFieldWithModel,
} from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import {
    ANIMATION,
    AUDIO,
    CHAT,
    CONTACT,
    DOCUMENT,
    INACCESSIBLE_MESSAGE,
    INLINE_KEYBOARD_MARKUP,
    LOCATION,
    MESSAGE_ORIGIN,
    PHOTO,
    REPLY_TO_MESSAGE,
    STICKER,
    STORY,
    TEXT_QUOTE,
    USER,
    VIDEO,
    VIDEO_NOTE,
    VOICE,
} from './telegram-trigger-field-models';

export const TELEGRAM_TRIGGER_FIELDS: Record<TelegramFieldParent, TelegramTriggerFieldWithModel[]> = {
    message: [
        {
            field_name: 'message_id',
            field_type: 'Integer',
            description:
                'Unique message identifier inside this chat. In specific instances (e.g., message containing a video sent to a big chat), the server might automatically schedule a message instead of sending it immediately. In such cases, this field will be 0 and the relevant message will be unusable until it is actually sent',
            model: 1,
        },
        {
            field_name: 'from',
            field_type: 'User',
            description:
                'Optional. Sender of the message; may be empty for messages sent to channels. For backward compatibility, if the message was sent on behalf of a chat, the field contains a fake sender user in non-channel chats',
            model: USER,
        },
        {
            field_name: 'date',
            field_type: 'Integer',
            description:
                'Date the message was sent in Unix time. It is always a positive number, representing a valid date.',
            model: 1710000000,
        },
        {
            field_name: 'chat',
            field_type: 'Chat',
            description: 'Chat the message belongs to',
            model: CHAT,
        },
        {
            field_name: 'forward_origin',
            field_type: 'MessageOrigin',
            description: 'Optional. Information about the original message for forwarded messages',
            model: MESSAGE_ORIGIN,
        },
        {
            field_name: 'reply_to_message',
            field_type: 'Message',
            description:
                'Optional. For replies in the same chat and message thread, the original message. Note that the Message object in this field will not contain further reply_to_message fields even if it itself is a reply.',
            model: REPLY_TO_MESSAGE,
        },
        {
            field_name: 'quote',
            field_type: 'TextQuote',
            description:
                'Optional. For replies that quote part of the original message, the quoted part of the message',
            model: TEXT_QUOTE,
        },
        {
            field_name: 'edit_date',
            field_type: 'Integer',
            description: 'Optional. Date the message was last edited in Unix time',
            model: 1710000000,
        },
        {
            field_name: 'is_from_offline',
            field_type: 'TRUE',
            description:
                'Optional. True, if the message was sent by an implicit action, for example, as an away or a greeting business message, or as a scheduled message',
            model: true,
        },
        {
            field_name: 'text',
            field_type: 'String',
            description: 'Optional. For text messages, the actual UTF-8 text of the message',
            model: 'Hello world',
        },
        {
            field_name: 'entities',
            field_type: 'Array[MessageEntity]',
            description:
                'Optional. For text messages, special entities like usernames, URLs, bot commands, etc. that appear in the text',
            model: ['MessageEntity'],
        },
        {
            field_name: 'animation',
            field_type: 'Animation',
            description:
                'Optional. Message is an animation, information about the animation. For backward compatibility, when this field is set, the document field will also be set',
            model: ANIMATION,
        },
        {
            field_name: 'audio',
            field_type: 'Audio',
            description: 'Optional. Message is an audio file, information about the file',
            model: AUDIO,
        },
        {
            field_name: 'document',
            field_type: 'Document',
            description: 'Optional. Message is a general file, information about the file',
            model: DOCUMENT,
        },
        {
            field_name: 'photo',
            field_type: 'Array[PhotoSize]',
            description: 'Optional. Message is a photo, available sizes of the photo',
            model: [PHOTO],
        },
        {
            field_name: 'sticker',
            field_type: 'Sticker',
            description: 'Optional. Message is a sticker, information about the sticker',
            model: STICKER,
        },
        {
            field_name: 'story',
            field_type: 'Story',
            description: 'Optional. Message is a forwarded story',
            model: STORY,
        },
        {
            field_name: 'video',
            field_type: 'Video',
            description: 'Optional. Message is a video, information about the video',
            model: VIDEO,
        },
        {
            field_name: 'video_note',
            field_type: 'VideoNote',
            description: 'Optional. Message is a video note, information about the video message',
            model: VIDEO_NOTE,
        },
        {
            field_name: 'voice',
            field_type: 'Voice',
            description: 'Optional. Message is a voice message, information about the file',
            model: VOICE,
        },
        {
            field_name: 'caption',
            field_type: 'String',
            description: 'Optional. Caption for the animation, audio, document, paid media, photo, video or voice',
            model: 'Caption for the animation, audio, document, paid media, photo, video or voice',
        },
        {
            field_name: 'caption_entities',
            field_type: 'Array[MessageEntity]',
            description:
                'Optional. For messages with a caption, special entities like usernames, URLs, bot commands, etc. that appear in the caption',
            model: ['MessageEntityModel'],
        },
        {
            field_name: 'contact',
            field_type: 'Contact',
            description: 'Optional. Message is a shared contact, information about the contact',
            model: CONTACT,
        },
        {
            field_name: 'location',
            field_type: 'Location',
            description: 'Optional. Message is a shared location, information about the location',
            model: LOCATION,
        },
        {
            field_name: 'reply_markup',
            field_type: 'InlineKeyboardMarkup',
            description:
                'Optional. Inline keyboard attached to the message. login_url buttons are represented as ordinary url buttons.',
            model: INLINE_KEYBOARD_MARKUP,
        },
    ],
    callback_query: [
        {
            field_name: 'id',
            field_type: 'String',
            description: 'Unique identifier for this query',
            model: 'unique-id',
        },
        {
            field_name: 'from',
            field_type: 'User',
            description: 'Sender',
            model: USER,
        },
        {
            field_name: 'message',
            field_type: 'MaybeInaccessibleMessage',
            description: 'Optional. Message sent by the bot with the callback button that originated the query',
            model: INACCESSIBLE_MESSAGE,
        },
        {
            field_name: 'data',
            field_type: 'String',
            description:
                'Optional. Data associated with the callback button. Be aware that the message originated the query can contain no callback buttons with this data.',
            model: 'Data associated with the callback button. Be aware that the message originated the query can contain no callback buttons with this data.',
        },
    ],
};

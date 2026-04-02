export const USER = {
    id: 1,
    is_bot: true,
    first_name: 'Jane',
    last_name: 'Doe',
    username: 'Jane_Doe',
    language_code: 'en',
    is_premium: true,
    added_to_attachment_menu: true,
    can_join_groups: true,
    can_read_all_group_messages: true,
    supports_inline_queries: true,
    can_connect_to_business: true,
    has_main_web_app: true,
    has_topics_enabled: true,
};

export const CHAT = {
    id: 1,
    type: 'private',
    title: 'Chat Title',
    username: 'Jane_Doe',
    first_name: 'Private Chat First Name',
    last_name: 'Private Chat Last Name',
    is_forum: true,
    is_direct_messages: true,
};

export const MESSAGE_ORIGIN = {
    type: 'user',
    date: 1710000000,
    sender_user: 'UserModel',
};

export const REPLY_TO_MESSAGE = {
    message_id: 1,
    message_thread_id: 1,
    direct_messages_topic: 'DirectMessageTopicModel',
    from: 'UserModel',
    sender_chat: 'ChatModel',
    sender_boost_count: 0,
    sender_business_bot: 'UserModel',
    chat: 'ChatModel',
    forward_origin: 'MessageOriginModel',
    is_topic_message: true,
    is_automatic_forward: true,
    reply_to_message: 'MessageModel',
    external_reply: 'ExternalReplyModel',
    quote: 'TextQuoteModel',
    reply_to_story: 'StoryModel',
    reply_to_checklist_task_id: 2,
    via_bot: 'UserModel',
    edit_date: 1710000000,
    has_protected_content: true,
    is_from_offline: true,
    is_paid_post: true,
    media_group_id: 'unique-id',
    author_signature: 'Signature',
    paid_star_count: 5,
    text: 'Text',
    entities: ['MessageEntityModel'],
    link_preview_options: 'LinkPreviewOptionsModel',
    suggested_post_info: 'SuggestedPostInfoModel',
    effect_id: 'unique-id',
    animation: 'AnimationModel',
    audio: 'AudioModel',
    document: 'DocumentModel',
    paid_media: 'PaidMediaInfoModel',
    photo: ['PhotoModel'],
    sticker: 'StickerModel',
    story: 'StoryModel',
    video: 'VideoModel',
    video_note: 'VideoNoteModel',
    voice: 'VoiceModel',
    caption: 'Caption for the animation, audio, document, paid media, photo, video or voice',
    caption_entities: ['MessageEntityModel'],
    show_caption_above_media: true,
    has_media_spoiler: true,
    checklist: 'ChecklistModel',
    contact: 'ContactModel',
    dice: 'DiceModel',
    game: 'GameModel',
    poll: 'PollModel',
    venue: 'VenueModel',
    location: 'LocationModel',
    new_chat_members: ['UserModel'],
    left_chat_member: 'UserModel',
    new_chat_title: 'New Chat Title',
    new_chat_photo: ['PhotoSizeModel'],
    delete_chat_photo: true,
    group_chat_created: true,
    supergroup_chat_created: true,
    channel_chat_created: true,
    message_auto_delete_timer_changed: 'MessageAutoDeleteTimerChangedModel',
    migrate_to_chat_id: 10,
    migrate_from_chat_id: 10,
    pinned_message: 'MaybeInaccessibleMessageModel',
    invoice: 'InvoiceModel',
    successful_payment: 'SuccessfulPaymentModel',
    refunded_payment: 'RefundedPaymentModel',
    users_shared: 'UsersSharedModel',
    chat_shared: 'ChatSharedModel',
    gift: 'GiftInfoModel',
    unique_gift: 'UniqueGiftInfoModel',
    gift_upgrade_sent: 'GiftInfoModel',
    connected_website: 'domain-name',
    write_access_allowed: 'WriteAccessAllowedModel',
    passport_data: 'PassportDataModel',
    proximity_alert_triggered: 'ProximityAlertTriggeredModel',
    boost_added: 'ChatBoostAddedModel',
    chat_background_set: 'ChatBackgroundModel',
    checklist_tasks_done: 'ChecklistTasksDoneModel',
    checklist_tasks_added: 'ChecklistTasksAddedModel',
    direct_message_price_changed: 'DirectMessagePriceChangedModel',
    forum_topic_created: 'ForumTopicCreatedModel',
    forum_topic_edited: 'ForumTopicEditedModel',
    forum_topic_closed: 'ForumTopicClosedModel',
    forum_topic_reopened: 'ForumTopicReopenedModel',
    general_forum_topic_hidden: 'GeneralForumTopicHiddenModel',
    general_forum_topic_unhidden: 'GeneralForumTopicUnhiddenModel',
    giveaway_created: 'GiveawayCreatedModel',
    giveaway: 'GiveawayModel',
    giveaway_winners: 'GiveawayWinnersModel',
    giveaway_completed: 'GiveawayCompletedModel',
    paid_message_price_changed: 'PaidMessagePriceChangedModel',
    suggested_post_approved: 'SuggestedPostApprovedModel',
    suggested_post_approval_failed: 'SuggestedPostApprovalFailedModel',
    suggested_post_declined: 'SuggestedPostDeclinedModel',
    suggested_post_paid: 'SuggestedPostPaidModel',
    suggested_post_refunded: 'SuggestedPostRefundedModel',
    video_chat_scheduled: 'VideoChatScheduledModel',
    video_chat_started: 'VideoChatStartedModel',
    video_chat_ended: 'VideoChatEndedModel',
    video_chat_participants_invited: 'VideoChatParticipantsInvitedModel',
    web_app_data: 'WebAppDataModel',
    reply_markup: 'InlineKeyboardMarkupModel',
};

export const TEXT_QUOTE = {
    text: 'Text of the quoted part of a message that is replied to by the given message',
    entities: ['MessageEntity'],
    position: 3,
    is_manual: true,
};

export const ANIMATION = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    width: 200,
    height: 400,
    duration: 120,
    thumbnail: 'PhotoSizeModel',
    file_name: 'gif-name.gif',
    mime_type: 'image/gif',
    file_size: 2097152,
};

export const AUDIO = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    duration: 120,
    performer: 'Artist Name',
    title: 'Audio Title',
    file_name: 'audio.mp3',
    mime_type: 'audio/mpeg',
    file_size: 2097152,
    thumbnail: 'PhotoSizeModel',
};

export const DOCUMENT = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    thumbnail: 'PhotoSizeModel',
    file_name: 'document.pdf',
    mime_type: 'application/pdf',
    file_size: 2097152,
};

export const PHOTO = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    width: 200,
    height: 400,
    file_size: 2097152,
};

export const STICKER = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    type: 'mask',
    width: 200,
    height: 400,
    is_animated: false,
    is_video: false,
    thumbnail: 'PhotoSizeModel',
    emoji: 'Emoji associated with the sticker',
    set_name: 'Name of the sticker set to which the sticker belongs',
    premium_animation: 'FileModel',
    mask_position: 'MaskPositionModel',
    custom_emoji_id: 'custom-emoji-id',
    needs_repairing: true,
    file_size: 2097152,
};

export const STORY = {
    chat: 'ChatModel',
    id: 1,
};

export const VIDEO = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    width: 200,
    height: 400,
    duration: 120,
    thumbnail: 'PhotoSizeModel',
    cover: ['PhotoSizeModel'],
    start_timestamp: 0,
    file_name: 'video-name.mp4',
    mime_type: 'video/mp4',
    file_size: 2097152,
};

export const VIDEO_NOTE = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    length: 200,
    duration: 120,
    thumbnail: 'PhotoSizeModel',
    file_size: 2097152,
};

export const VOICE = {
    file_id: 'file-id',
    file_unique_id: 'file-unique-unique-id',
    duration: 120,
    mime_type: 'audio/mpeg',
    file_size: 2097152,
};

export const CONTACT = {
    phone_number: '+12345678901',
    first_name: 'Jane',
    last_name: 'Doe',
    user_id: 10,
    vcard: 'Additional data about the contact in the form of a vCard',
};

export const LOCATION = {
    latitude: 50.4501,
    longitude: 30.5234,
    horizontal_accuracy: 50,
    live_period: 300,
    heading: 90,
    proximity_alert_radius: 100,
};

export const INLINE_KEYBOARD_MARKUP = {
    'inline-keyboard': [['InlineKeyboardButtonModel']],
};

export const INACCESSIBLE_MESSAGE = {
    chat: 'ChatModel',
    message_id: 1,
    date: 0,
};

"""The models of Aula's data, and the parsers that read them from Aula's answers."""

from .constants import AulaCalendarEventType

from .aula_birthday_parser import AulaBirthdayParser
from .aula_calendar_parser import AulaCalendarParser
from .aula_event_detail_parser import AulaEventDetailParser
from .aula_message_thread_parser import AulaMessageThreadParser
from .aula_notification_parser import AulaNotificationParser
from .aula_presence_parser import AulaPresenceParser
from .aula_profile_parser import AulaProfileParser
from .aula_post_parser import AulaPostParser
from .aula_vacation_parser import AulaVacationParser
from .aula_weekly_plan_parser import AulaWeeklyPlanParser
from .aula_easyiq_weekplan_parser import AulaEasyiqWeekplanParser
from .aula_newsletter_parser import AulaNewsletterParser

from .aula_birthday_models import (
    AulaBirthdayEvent,
)
from .aula_calendar_models import (
    AulaCalendarEvent,
    AulaCalendarEventLesson,
    AulaCalendarEventLessonParticipant,
    AulaCalendarEventResource,
    AulaCalendarEventTimeSlot,
    AulaCalendarEventTimeSlotEntry,
    AulaCalendarEventTimeSlotEntryAnswer,
    AulaCalendarEventTimeSlotEntryIndex,
)
from .aula_event_detail_models import (
    AulaEventBooking,
    AulaEventDetail,
    AulaEventInvitation,
)
from .aula_message_thread_models import (
    AulaMessage,
    AulaMessageText,
    AulaMessageThread,
    AulaThreadRecipient,
    AulaThreadRegardingChild,
)
from .aula_notification_models import(
    AulaNotificationBase,
    AulaAlbumNotification,
    AulaCalendarEventNotification,
    AulaGalleryNotification,
    AulaMessageNotification,
    AulaPostNotification,
    AulaPresenceNotification,
    NotificationArea,
    NotificationType,
    NotificationEventType,
    AULA_NOTIFICATION_TYPES,
)
from .aula_presence_models import (
    AulaPresenceConfiguration,
    AulaPresenceModuleType,
    AulaPresencePermission,
    AulaPresenceStatus,
    AulaSickReportCheck,
    AulaSickReportRoute,
)
from .aula_post_models import (
    AulaClosedDay,
    AulaOpeningDay,
    AulaPost,
    AulaPostAttachment,
    AulaPosts,
)
from .aula_vacation_models import (
    AulaVacation,
    AulaVacationDay,
    AulaVacationRequest,
    AulaVacationRequestDetail,
)
from .aula_profile_models import (
    AulaChildProfile,
    AulaDailyOverview,
    AulaInstitutionGroup,
    AulaInstitutionProfile,
    AulaLocation,
    AulaLoginData,
    AulaProfile,
    AulaProfilePicture,
    AulaProfileRelation,
    AulaToken,
    AulaWidget,
)
from .aula_weekly_plan_models import(
    AulaWeeklyPlan,
    AulaDailyPlan,
    AulaDailyPlanTask
)
from .aula_easyiq_weekplan_models import (
    AulaEasyiqWeeklyPlan,
    AulaEasyiqDailyPlan,
    AulaEasyiqEvent,
)
from .aula_newsletter_models import (
    AulaNewsletter,
    AulaWeeklyNewsletter,
)

# Add other imports here as needed

__all__ = [
    #constants
    'AulaCalendarEventType',

    #parsers
    'AulaBirthdayParser',
    'AulaCalendarParser',
    'AulaEventDetailParser',
    'AulaMessageThreadParser',
    'AulaNotificationParser',
    'AulaPresenceParser',
    'AulaProfileParser',
    'AulaPostParser',
    'AulaVacationParser',
    'AulaWeeklyPlanParser',
    'AulaEasyiqWeekplanParser',
    'AulaNewsletterParser',

    #models
    #birthday
    'AulaBirthdayEvent',
    #calendar
    'AulaCalendarEvent',
    'AulaCalendarEventLesson',
    'AulaCalendarEventLessonParticipant',
    'AulaCalendarEventResource',
    'AulaCalendarEventTimeSlot',
    'AulaCalendarEventTimeSlotEntry',
    'AulaCalendarEventTimeSlotEntryAnswer',
    'AulaCalendarEventTimeSlotEntryIndex',
    'AulaEventBooking',
    'AulaEventDetail',
    'AulaEventInvitation',
    #message
    'AulaMessage',
    'AulaMessageText',
    'AulaMessageThread',
    'AulaThreadRecipient',
    'AulaThreadRegardingChild',
    #notification
    'AulaNotificationBase',
    'AulaAlbumNotification',
    'AulaCalendarEventNotification',
    'AulaGalleryNotification',
    'AulaMessageNotification',
    'AulaPostNotification',
    'AulaPresenceNotification',
    'NotificationArea',
    'NotificationEventType',
    'NotificationType',
    'AULA_NOTIFICATION_TYPES',
    #presence
    'AulaPresenceConfiguration',
    'AulaPresenceModuleType',
    'AulaPresencePermission',
    'AulaPresenceStatus',
    'AulaSickReportCheck',
    'AulaSickReportRoute',
    #posts
    'AulaClosedDay',
    'AulaOpeningDay',
    'AulaPost',
    'AulaPostAttachment',
    'AulaPosts',
    #vacation
    'AulaVacation',
    'AulaVacationDay',
    'AulaVacationRequest',
    'AulaVacationRequestDetail',
    #profile
    'AulaChildProfile',
    'AulaDailyOverview',
    'AulaInstitutionGroup',
    'AulaInstitutionProfile',
    'AulaLocation',
    'AulaLoginData',
    'AulaProfile',
    'AulaProfilePicture',
    'AulaProfileRelation',
    'AulaToken',
    'AulaWidget',
    #weekly_plan (Meebook)
    'AulaWeeklyPlan',
    'AulaDailyPlan',
    'AulaDailyPlanTask',
    #easyiq_weekplan
    'AulaEasyiqWeeklyPlan',
    'AulaEasyiqDailyPlan',
    'AulaEasyiqEvent',
    #newsletter (MinUddannelse)
    'AulaNewsletter',
    'AulaWeeklyNewsletter',
]
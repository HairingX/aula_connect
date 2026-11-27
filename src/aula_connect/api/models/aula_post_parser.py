"""Reading Aula's posts, closed days and opening hours into the models."""

from datetime import datetime
from typing import Any, List

from ..responses.get_all_posts_response import AulaGetAllPostsResponse, AulaPostAttachmentData, AulaPostData
from ..responses.get_opening_hours_response import AulaGetClosedDaysResponse, AulaGetOpeningHoursResponse
from .aula_parser import AulaParser
from .aula_post_models import AulaClosedDay, AulaOpeningDay, AulaPost, AulaPostAttachment, AulaPosts


class AulaPostParser(AulaParser):
    """Reads the news feed's posts, and the days and hours institutions are open."""

    @staticmethod
    def parse_posts_response(data: AulaGetAllPostsResponse) -> AulaPosts:
        """The posts in Aula's answer, in its order, and when the guardian last saw them."""
        parse = AulaPostParser
        page = data["data"]
        return AulaPosts(
            posts=[parse.parse_post(post) for post in page.get("posts") or []],
            last_seen=parse._parse_nullable_datetime(page.get("profileLastSeenPostDate") or None, fix_timezone=False),
            has_more=parse._parse_bool(page.get("hasMorePosts")),
        )

    @staticmethod
    def parse_post(post: AulaPostData) -> AulaPost:
        """A post."""
        parse = AulaPostParser
        owner = post.get("ownerProfile") or {}
        return AulaPost(
            id=parse._parse_int(post.get("id")),
            title=parse._parse_str(post.get("title")),
            html=parse._parse_str((post.get("content") or {}).get("html")),
            timestamp=parse._parse_datetime(post.get("timestamp"), fix_timezone=False),
            publish_at=parse._moment(post.get("publishAt")),
            edited_at=parse._moment(post.get("editedAt")),
            expire_at=parse._moment(post.get("expireAt")),
            is_important=parse._parse_bool(post.get("isImportant")),
            important_from=parse._parse_nullable_date(post.get("importantFrom") or None),
            important_to=parse._parse_nullable_date(post.get("importantTo") or None),
            author=owner.get("fullName") or None,
            institution=(owner.get("institution") or {}).get("institutionName") or None,
            groups=[name for group in post.get("sharedWithGroups") or [] if (name := group.get("name"))],
            attachments=[parse._attachment(attachment) for attachment in post.get("attachments") or []],
            comment_count=parse._parse_int(post.get("commentCount") or 0),
            children=[
                child_id for related in post.get("relatedProfiles") or []
                if related.get("role") == "child" and isinstance(child_id := related.get("id"), int)
            ],
        )

    @staticmethod
    def _moment(value: Any) -> datetime | None:
        return AulaPostParser._parse_nullable_datetime(value or None, fix_timezone=False)

    @staticmethod
    def _attachment(attachment: AulaPostAttachmentData) -> AulaPostAttachment:
        media = attachment.get("media")
        file = (media or {}).get("file") if media else attachment.get("file")
        return AulaPostAttachment(
            name=AulaPostParser._parse_str(attachment.get("name") or (file or {}).get("name")),
            url=(file or {}).get("url") or None,
            thumbnail_url=(media.get("largeThumbnailUrl") or media.get("thumbnailUrl") or None) if media else None,
            is_media=media is not None,
        )

    @staticmethod
    def parse_closed_days_response(data: AulaGetClosedDaysResponse) -> List[AulaClosedDay]:
        """Each institution's closed days in Aula's answer, in its order."""
        parse = AulaPostParser
        return [
            AulaClosedDay(
                institution_code=parse._parse_str(institution.get("institutionCode")),
                name=parse._parse_str(closed.get("name")),
                start_date=parse._parse_date(closed.get("startDate")),
                end_date=parse._parse_date(closed.get("endDate") or closed.get("startDate")),
            )
            for institution in data["data"].get("institutionClosedDays") or []
            for closed in (institution.get("closedDaysOverview") or {}).get("closedDays") or []
            if closed.get("startDate")
        ]

    @staticmethod
    def parse_opening_hours_response(data: AulaGetOpeningHoursResponse) -> List[AulaOpeningDay]:
        """Each institution's hours, day by day, in Aula's answer."""
        parse = AulaPostParser
        return [
            AulaOpeningDay(
                institution_code=parse._parse_str(institution.get("institutionCode")),
                day=parse._parse_date(day.get("date")),
                kind=parse._parse_str(day.get("type")),
                open_time=parse._parse_nullable_time(day.get("openTime") or None, fix_timezone=False),
                close_time=parse._parse_nullable_time(day.get("closeTime") or None, fix_timezone=False),
            )
            for institution in data["data"].get("openingHoursOverviewDto") or []
            for day in institution.get("openingHoursDto") or []
            if day.get("date")
        ]

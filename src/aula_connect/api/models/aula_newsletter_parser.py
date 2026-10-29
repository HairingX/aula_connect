"""Reading MinUddannelse's weekly newsletters into the models."""

from datetime import timedelta, date
from hashlib import sha256
from typing import List

from ..responses.get_weekly_newsletter_response import (
    AulaGetWeeklyNewsletterResponse,
    AulaWeeklyNewsletterPersonData,
)
from ..utils.list_utils import list_without_none

from .aula_newsletter_models import AulaNewsletter, AulaWeeklyNewsletter
from .aula_parser import AulaParser


class AulaNewsletterParser(AulaParser):
    """Reads MinUddannelse's weekly newsletters."""
    @staticmethod
    def parse_person(data: AulaWeeklyNewsletterPersonData, from_date: date) -> AulaWeeklyNewsletter | None:
        """A child's newsletters of the week from `from_date`, each with an id stable across reads; None for a child with no name or none."""
        full_name = AulaNewsletterParser._parse_str(data.get("navn"))
        if not full_name:
            return None

        institutions = data.get("institutioner")
        if not institutions:
            return None

        weekno = from_date.strftime("%Y-W%V")
        newsletters: List[AulaNewsletter] = []

        for institution in institutions:
            inst_name = AulaNewsletterParser._parse_str(institution.get("institution"))
            newsletter_list = institution.get("ugebreve")
            if not newsletter_list:
                continue
            for newsletter in newsletter_list:
                indhold = newsletter.get("indhold", "")
                if not indhold:
                    continue
                raw = "|".join([full_name, weekno, inst_name or "", indhold])
                newsletter_id = sha256(raw.encode()).hexdigest()[:16]
                newsletters.append(AulaNewsletter(
                    id=newsletter_id,
                    content_html=indhold,
                    institution_name=inst_name,
                ))

        if not newsletters:
            return None

        return AulaWeeklyNewsletter(
            child_name=full_name,
            from_date=from_date,
            to_date=from_date + timedelta(days=6),
            newsletters=newsletters,
        )

    @staticmethod
    def parse_response(data: AulaGetWeeklyNewsletterResponse | None, from_date: date) -> List[AulaWeeklyNewsletter]:
        """The children's newsletters of MinUddannelse's answer for the week from `from_date`."""
        if not data:
            return []
        personer = data.get("personer")
        if not personer:
            return []
        return list_without_none([
            AulaNewsletterParser.parse_person(person, from_date)
            for person in personer
        ])
